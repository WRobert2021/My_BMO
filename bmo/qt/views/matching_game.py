"""QML adapter for the Pup Pairs matching game."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, QUrl

from bmo.matching_game_core import (
    BmoMemoryPlayer,
    CARD_BACK_PATH,
    CHARACTER_FILES,
    MatchingGameHistory,
    MatchingGameModel,
    PAW_PATROL_DIR,
)
from bmo.qt.views.base import QtHostedView


class QtMatchingGameView(QtHostedView):
    kind = "matching_game"
    title = "Pup Pairs"

    def __init__(
        self,
        host: Any,
        *,
        embedded: bool = False,
        on_close: Any = None,
        announce: Any = None,
        on_player_change: Any = None,
        history: Any = None,
        face_provider: Any = None,
    ) -> None:
        del embedded, face_provider
        self.announce = announce or (lambda _text: None)
        self.on_player_change = on_player_change or (lambda _player: None)
        self.history = history or MatchingGameHistory()
        self.pair_count = self.history.pair_count
        self.model = MatchingGameModel(CHARACTER_FILES[: self.pair_count])
        self.bmo = BmoMemoryPlayer()
        self.status = "Your turn."
        self.locked = False
        self._recorded = False
        super().__init__(host, on_close=on_close or (lambda: None))

    def payload(self) -> dict[str, object]:
        return {
            "cardBackSource": QUrl.fromLocalFile(str(CARD_BACK_PATH.resolve())),
            "cards": [
                {
                    "id": card.card_id,
                    "source": QUrl.fromLocalFile(str((PAW_PATROL_DIR / card.character).resolve())),
                    "revealed": card.card_id in self.model.face_up or card.card_id in self.model.matched,
                    "matched": card.card_id in self.model.matched,
                }
                for card in self.model.cards
            ],
            "humanScore": self.model.scores["human"],
            "bmoScore": self.model.scores["bmo"],
            "moves": self.model.moves,
            "status": self.status,
            "complete": self.model.complete,
            "locked": self.locked,
            "pairCount": self.pair_count,
        }

    def handle_action(self, action: str, value: str) -> None:
        if action == "matching_card":
            try:
                self._human_reveal(int(value))
            except ValueError:
                return
        elif action == "matching_restart":
            self._new_game(self.pair_count)
        elif action == "matching_difficulty":
            try:
                self._new_game(self.history.set_pair_count(int(value)))
            except ValueError:
                return
        else:
            super().handle_action(action, value)

    def _new_game(self, pair_count: int) -> None:
        self.pair_count = pair_count
        self.model.set_characters(CHARACTER_FILES[:pair_count])
        self.bmo.reset()
        self.status = "Your turn."
        self.locked = False
        self._recorded = False
        self.on_player_change("human")
        self.refresh()

    def _human_reveal(self, card_id: int) -> None:
        if self.locked or self.model.current_player != "human" or self.model.complete:
            return
        result = self.model.reveal(card_id)
        if result == "ignored":
            return
        self.bmo.observe(card_id, self.model.cards[card_id].character)
        self.refresh()
        if result == "match":
            self.bmo.forget_matched(self.model.matched)
            if self._finish_if_complete():
                return
            self.status = "You found a pair! Go again."
            self.refresh()
        elif result == "miss":
            self.locked = True
            self.status = "BMO's turn next."
            self.refresh()
            QTimer.singleShot(650, self._begin_bmo_turn)

    def _begin_bmo_turn(self) -> None:
        if self.closed:
            return
        self.model.hide_unmatched()
        self.on_player_change("bmo")
        self.status = "BMO's turn."
        self.refresh()
        QTimer.singleShot(350, self._bmo_first)

    def _bmo_first(self) -> None:
        if self.closed or self.model.complete:
            return
        card_id = self.bmo.choose_first(self.model)
        self.model.reveal(card_id)
        self.bmo.observe(card_id, self.model.cards[card_id].character)
        self.refresh()
        QTimer.singleShot(550, lambda: self._bmo_second(card_id))

    def _bmo_second(self, first_id: int) -> None:
        if self.closed or self.model.complete:
            return
        card_id = self.bmo.choose_second(self.model, first_id)
        result = self.model.reveal(card_id)
        self.bmo.observe(card_id, self.model.cards[card_id].character)
        self.refresh()
        if result == "match":
            self.bmo.forget_matched(self.model.matched)
            if self._finish_if_complete():
                return
            self.status = "BMO found a pair!"
            self.refresh()
            QTimer.singleShot(650, self._bmo_first)
        else:
            QTimer.singleShot(650, self._end_bmo_turn)

    def _end_bmo_turn(self) -> None:
        if self.closed:
            return
        self.model.hide_unmatched()
        self.locked = False
        self.status = "Your turn."
        self.on_player_change("human")
        self.refresh()

    def _finish_if_complete(self) -> bool:
        if not self.model.complete:
            return False
        self.locked = True
        human = self.model.scores["human"]
        bmo = self.model.scores["bmo"]
        if human > bmo:
            self.status = "You win! Great matching!"
            spoken = "You win! Great game!"
        elif bmo > human:
            self.status = "BMO wins! Great game!"
            spoken = "BMO wins! Great game!"
        else:
            self.status = "It's a tie! Great game!"
            spoken = "It's a tie! Great game!"
        if not self._recorded:
            self._recorded = True
            self.history.record_game(
                pairs=self.pair_count,
                human_score=human,
                bmo_score=bmo,
                moves=self.model.moves,
                seconds=self.model.elapsed_seconds,
            )
        self.on_player_change("speaking")
        self.announce(spoken)
        self.refresh()
        return True


__all__ = ["QtMatchingGameView"]
