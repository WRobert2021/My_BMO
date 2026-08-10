"""Touch album grid, fullscreen photo actions, and vision presentation."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterable
from pathlib import Path

from PIL import Image, ImageOps, ImageTk

from bmo.ui.gestures import GestureKind, HorizontalSwipeRecognizer


WINDOW_WIDTH = 800
WINDOW_HEIGHT = 480
FACE_BOUNDS = (636, 76, 792, 182)
GRID_BOUNDS = (24, 76, 612, 448)

PhotoProvider = Callable[[], Iterable[Path]]
PhotoDeleter = Callable[[Path], Path]
FaceProvider = Callable[[], Image.Image | None]
VisionRequester = Callable[[Path, Callable[[], None]], None]


class AlbumPaginator:
    """Keep photo pagination independent from Tk rendering."""

    def __init__(self, photos_per_page: int = 6) -> None:
        if photos_per_page < 2 or photos_per_page > 6:
            raise ValueError("Album photos_per_page must be between 2 and 6.")
        self.photos_per_page = photos_per_page
        self.photos: tuple[Path, ...] = ()
        self.page_index = 0

    @property
    def page_count(self) -> int:
        if not self.photos:
            return 1
        return (
            len(self.photos) + self.photos_per_page - 1
        ) // self.photos_per_page

    @property
    def current_photos(self) -> tuple[Path, ...]:
        offset = self.page_index * self.photos_per_page
        return self.photos[offset : offset + self.photos_per_page]

    def replace(self, photos: Iterable[Path]) -> None:
        self.photos = tuple(Path(photo) for photo in photos)
        self.page_index = min(self.page_index, self.page_count - 1)

    def swipe_left(self) -> bool:
        if self.page_index >= self.page_count - 1:
            return False
        self.page_index += 1
        return True

    def swipe_right(self) -> bool:
        if self.page_index <= 0:
            return False
        self.page_index -= 1
        return True


class AlbumApp:
    """Browse configured photos and launch actions for one selected image."""

    BACKGROUND = "#e7f7ff"
    NAVY = "#102a5e"
    BLUE = "#1578d3"
    WHITE = "#ffffff"
    MUTED = "#58708c"
    DANGER = "#c83a4a"
    BLACK = "#000000"
    COLUMNS = 3
    ROWS = 2
    TILE_PADDING = 8
    ACTION_BACK_BOUNDS = (42, 367, 246, 451)
    ACTION_DELETE_BOUNDS = (298, 367, 502, 451)
    ACTION_BMO_BOUNDS = (554, 367, 758, 451)
    FACE_REFRESH_MS = 150

    def __init__(
        self,
        root: tk.Misc,
        *,
        photo_provider: PhotoProvider,
        delete_photo: PhotoDeleter,
        face_provider: FaceProvider,
        request_vision: VisionRequester,
        bmo_button_path: Path,
        photos_per_page: int = 6,
        on_close: Callable[[], None],
    ) -> None:
        self.root = root
        self.photo_provider = photo_provider
        self.delete_photo = delete_photo
        self.face_provider = face_provider
        self.request_vision = request_vision
        self.bmo_button_path = Path(bmo_button_path)
        self.on_close = on_close
        self.paginator = AlbumPaginator(photos_per_page)
        self.gesture = HorizontalSwipeRecognizer()
        self.view = "grid"
        self.selected_photo: Path | None = None
        self.closed = False
        self.face_after_id: str | None = None
        self.face_item: int | None = None
        self.face_fallback_item: int | None = None
        self.face_image: ImageTk.PhotoImage | None = None
        self._photo_bounds: tuple[
            tuple[tuple[int, int, int, int], Path], ...
        ] = ()
        self._image_refs: list[ImageTk.PhotoImage] = []

        self.canvas = tk.Canvas(
            root,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            bg=self.BACKGROUND,
            highlightthickness=0,
        )
        self.canvas.place(
            x=0,
            y=0,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
        )
        self.canvas.bind("<ButtonPress-1>", self._handle_press)
        self.canvas.bind("<ButtonRelease-1>", self._handle_release)
        self.refresh_photos()
        self._refresh_face()

    def refresh_photos(self) -> None:
        """Rescan the configured library and redraw its current page."""
        self.paginator.replace(self.photo_provider())
        self._show_grid()

    def _show_grid(self) -> None:
        self.view = "grid"
        self.selected_photo = None
        self._clear_canvas(self.BACKGROUND)
        self.canvas.create_rectangle(
            0,
            0,
            WINDOW_WIDTH,
            62,
            fill=self.NAVY,
            outline="",
        )
        self.canvas.create_text(
            24,
            30,
            anchor="w",
            text="ALBUM",
            fill=self.WHITE,
            font=("Arial Rounded MT Bold", 24, "bold"),
        )
        self.canvas.create_text(
            156,
            31,
            anchor="w",
            text=f"{len(self.paginator.photos)} PHOTOS",
            fill="#bde7ff",
            font=("Arial", 10, "bold"),
        )
        self._draw_face_panel()
        self._draw_photo_grid()

    def _draw_photo_grid(self) -> None:
        bounds_and_photos = []
        photos = self.paginator.current_photos
        if not photos:
            self.canvas.create_text(
                318,
                230,
                text="NO PHOTOS FOUND",
                fill=self.NAVY,
                font=("Arial Rounded MT Bold", 22, "bold"),
            )
            self.canvas.create_text(
                318,
                266,
                text="Add images to the configured Pictures folder.",
                fill=self.MUTED,
                font=("Arial", 11, "bold"),
            )
        for index, photo_path in enumerate(photos):
            tile_bounds = self._tile_bounds(index)
            bounds_and_photos.append((tile_bounds, photo_path))
            self._draw_thumbnail(photo_path, tile_bounds)
        self._photo_bounds = tuple(bounds_and_photos)
        self.canvas.create_text(
            318,
            463,
            text=(
                f"{self.paginator.page_index + 1} / "
                f"{self.paginator.page_count}"
            ),
            fill=self.MUTED,
            font=("Arial", 9, "bold"),
        )

    @classmethod
    def _tile_bounds(cls, index: int) -> tuple[int, int, int, int]:
        left, top, right, bottom = GRID_BOUNDS
        row, column = divmod(index, cls.COLUMNS)
        cell_width = (right - left) // cls.COLUMNS
        cell_height = (bottom - top) // cls.ROWS
        cell_left = left + column * cell_width
        cell_top = top + row * cell_height
        padding = cls.TILE_PADDING
        return (
            cell_left + padding,
            cell_top + padding,
            cell_left + cell_width - padding,
            cell_top + cell_height - padding,
        )

    def _draw_thumbnail(
        self,
        photo_path: Path,
        bounds: tuple[int, int, int, int],
    ) -> None:
        left, top, right, bottom = bounds
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=self.WHITE,
            outline="#98bfd7",
            width=3,
        )
        try:
            with Image.open(photo_path) as source:
                oriented = ImageOps.exif_transpose(source).convert("RGB")
            thumbnail = ImageOps.fit(
                oriented,
                (right - left - 8, bottom - top - 8),
                method=Image.Resampling.LANCZOS,
            )
            image = ImageTk.PhotoImage(thumbnail)
            self._image_refs.append(image)
            self.canvas.create_image(
                (left + right) // 2,
                (top + bottom) // 2,
                image=image,
                anchor=tk.CENTER,
            )
        except (OSError, ValueError, tk.TclError):
            self.canvas.create_text(
                (left + right) // 2,
                (top + bottom) // 2,
                text="?",
                fill=self.NAVY,
                font=("Arial Rounded MT Bold", 38, "bold"),
            )

    def _show_photo(self, photo_path: Path) -> None:
        self.view = "photo"
        self.selected_photo = Path(photo_path)
        self._draw_fullscreen_photo(show_bmo=False)

    def _draw_fullscreen_photo(self, *, show_bmo: bool) -> None:
        self._clear_canvas(self.BLACK)
        photo_path = self.selected_photo
        if photo_path is None:
            self.refresh_photos()
            return
        try:
            with Image.open(photo_path) as source:
                oriented = ImageOps.exif_transpose(source).convert("RGB")
            photo = ImageOps.contain(
                oriented,
                (WINDOW_WIDTH, WINDOW_HEIGHT),
                method=Image.Resampling.LANCZOS,
            )
            image = ImageTk.PhotoImage(photo)
            self._image_refs.append(image)
            self.canvas.create_image(
                WINDOW_WIDTH // 2,
                WINDOW_HEIGHT // 2,
                image=image,
                anchor=tk.CENTER,
            )
        except (OSError, ValueError, tk.TclError):
            self.canvas.create_text(
                WINDOW_WIDTH // 2,
                WINDOW_HEIGHT // 2,
                text="UNABLE TO OPEN PHOTO",
                fill=self.WHITE,
                font=("Arial Rounded MT Bold", 22, "bold"),
            )
        if show_bmo:
            self._draw_face_panel()

    def _show_action_menu(self, error: str | None = None) -> None:
        self.view = "actions"
        self._draw_fullscreen_photo(show_bmo=False)
        self.canvas.create_rectangle(
            0,
            342,
            WINDOW_WIDTH,
            WINDOW_HEIGHT,
            fill=self.NAVY,
            outline=self.WHITE,
            width=2,
        )
        self._draw_action_button(
            self.ACTION_BACK_BOUNDS,
            "BACK TO ALBUM",
            self.BLUE,
        )
        self._draw_action_button(
            self.ACTION_DELETE_BOUNDS,
            "MOVE TO\nWASTEBASKET",
            self.DANGER,
        )
        self._draw_bmo_action_button()
        if error:
            self.canvas.create_text(
                WINDOW_WIDTH // 2,
                352,
                text=error,
                fill="#ffd6d6",
                font=("Arial", 9, "bold"),
            )

    def _draw_action_button(
        self,
        bounds: tuple[int, int, int, int],
        label: str,
        color: str,
    ) -> None:
        left, top, right, bottom = bounds
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=color,
            outline=self.WHITE,
            width=2,
        )
        self.canvas.create_text(
            (left + right) // 2,
            (top + bottom) // 2,
            text=label,
            fill=self.WHITE,
            justify=tk.CENTER,
            font=("Arial Rounded MT Bold", 11, "bold"),
        )

    def _draw_bmo_action_button(self) -> None:
        left, top, right, bottom = self.ACTION_BMO_BOUNDS
        self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=self.WHITE,
            outline=self.WHITE,
            width=2,
        )
        try:
            with Image.open(self.bmo_button_path) as source:
                oriented = ImageOps.exif_transpose(source).convert("RGB")
            icon = ImageOps.fit(
                oriented,
                (right - left - 8, bottom - top - 8),
                method=Image.Resampling.LANCZOS,
            )
            image = ImageTk.PhotoImage(icon)
            self._image_refs.append(image)
            self.canvas.create_image(
                (left + right) // 2,
                (top + bottom) // 2,
                image=image,
                anchor=tk.CENTER,
            )
        except (OSError, ValueError, tk.TclError):
            self.canvas.create_text(
                (left + right) // 2,
                (top + bottom) // 2,
                text="ASK BMO",
                fill=self.NAVY,
                font=("Arial Rounded MT Bold", 12, "bold"),
            )

    def _begin_analysis(self) -> None:
        photo_path = self.selected_photo
        if photo_path is None:
            return
        self.view = "analyzing"
        self._draw_fullscreen_photo(show_bmo=True)
        try:
            self.request_vision(photo_path, self._finish_analysis)
        except Exception as exc:
            self._show_action_menu(f"BMO COULD NOT ANALYZE: {exc}")

    def _finish_analysis(self) -> None:
        if self.closed or self.selected_photo is None:
            return
        self.view = "photo"
        self._draw_fullscreen_photo(show_bmo=False)

    def _delete_selected_photo(self) -> None:
        photo_path = self.selected_photo
        if photo_path is None:
            return
        try:
            self.delete_photo(photo_path)
        except (OSError, PermissionError, ValueError) as exc:
            self._show_action_menu(f"COULD NOT MOVE PHOTO: {exc}")
            return
        self.paginator.replace(self.photo_provider())
        self._show_grid()

    def _draw_face_panel(self) -> None:
        self.canvas.create_rectangle(
            *FACE_BOUNDS,
            fill=self.NAVY,
            outline=self.WHITE,
            width=3,
        )
        self.face_item = self.canvas.create_image(714, 123, anchor=tk.CENTER)
        self.face_fallback_item = self.canvas.create_text(
            714,
            123,
            text="BMO",
            fill=self.WHITE,
            font=("Arial Rounded MT Bold", 20, "bold"),
        )

    def _refresh_face(self) -> None:
        if self.closed:
            return
        if self.face_item is not None and self.face_fallback_item is not None:
            try:
                face = self.face_provider()
                if face is not None:
                    resized = face.convert("RGB").resize(
                        (140, 84),
                        Image.Resampling.LANCZOS,
                    )
                    self.face_image = ImageTk.PhotoImage(resized)
                    self.canvas.itemconfigure(
                        self.face_item,
                        image=self.face_image,
                    )
                    self.canvas.itemconfigure(
                        self.face_fallback_item,
                        state=tk.HIDDEN,
                    )
            except (OSError, ValueError, tk.TclError):
                pass
        self.face_after_id = self.root.after(
            self.FACE_REFRESH_MS,
            self._refresh_face,
        )

    def _clear_canvas(self, background: str) -> None:
        self.canvas.configure(bg=background)
        self.canvas.delete("all")
        self.face_item = None
        self.face_fallback_item = None
        self.face_image = None
        self._photo_bounds = ()
        self._image_refs.clear()

    def _handle_press(self, event: tk.Event) -> str:
        self.gesture.press(int(event.x), int(event.y))
        return "break"

    def _handle_release(self, event: tk.Event) -> str:
        point = int(event.x), int(event.y)
        gesture = self.gesture.release(*point)
        if self.view == "grid":
            self._handle_grid_gesture(gesture, point)
        elif self.view == "photo" and gesture is GestureKind.TAP:
            self._show_action_menu()
        elif self.view == "actions" and gesture is GestureKind.TAP:
            self._handle_action_tap(point)
        return "break"

    def _handle_grid_gesture(
        self,
        gesture: GestureKind,
        point: tuple[int, int],
    ) -> None:
        if gesture is GestureKind.TAP and self._point_in(point, FACE_BOUNDS):
            self.close()
            return
        if gesture is GestureKind.TAP:
            for bounds, photo_path in self._photo_bounds:
                if self._point_in(point, bounds):
                    self._show_photo(photo_path)
                    return
        if gesture is GestureKind.SWIPE_LEFT and self.paginator.swipe_left():
            self._show_grid()
        elif (
            gesture is GestureKind.SWIPE_RIGHT
            and self.paginator.swipe_right()
        ):
            self._show_grid()

    def _handle_action_tap(self, point: tuple[int, int]) -> None:
        if self._point_in(point, self.ACTION_BACK_BOUNDS):
            self._show_grid()
        elif self._point_in(point, self.ACTION_DELETE_BOUNDS):
            self._delete_selected_photo()
        elif self._point_in(point, self.ACTION_BMO_BOUNDS):
            self._begin_analysis()

    @staticmethod
    def _point_in(
        point: tuple[int, int],
        bounds: tuple[int, int, int, int],
    ) -> bool:
        left, top, right, bottom = bounds
        return left <= point[0] <= right and top <= point[1] <= bottom

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.face_after_id is not None:
            try:
                self.root.after_cancel(self.face_after_id)
            except tk.TclError:
                pass
            self.face_after_id = None
        self.canvas.destroy()
        self.on_close()
