import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Basic as Basic

Item {
    id: musicView

    required property var controller
    property var viewModel: controller.viewData
    property string loadedBrowserRevision: ""
    property bool resetListOnNextSync: true

    ListModel { id: browserModel }

    function send(action, value) {
        controller.requestViewAction(
            action,
            value === undefined ? "" : String(value)
        )
    }

    function browse(mode) {
        resetListOnNextSync = true
        send("music_browse", mode)
    }

    function syncBrowser() {
        let revision = String(viewModel.browserRevision || "")
        if (revision === loadedBrowserRevision)
            return
        let savedY = songList.contentY
        browserModel.clear()
        let items = viewModel.browserItems || []
        for (let index = 0; index < items.length; ++index)
            browserModel.append(items[index])
        loadedBrowserRevision = revision
        Qt.callLater(function() {
            let maximum = Math.max(0, songList.contentHeight - songList.height)
            songList.contentY = resetListOnNextSync
                    ? 0 : Math.max(0, Math.min(savedY, maximum))
            resetListOnNextSync = false
        })
    }

    onViewModelChanged: syncBrowser()
    Component.onCompleted: syncBrowser()

    component MarqueeText: Item {
        id: marquee
        property alias text: marqueeLabel.text
        property alias color: marqueeLabel.color
        property alias font: marqueeLabel.font
        property int horizontalAlignment: Text.AlignLeft
        property bool running: true

        clip: true

        Text {
            id: marqueeLabel
            x: 0
            anchors.verticalCenter: parent.verticalCenter
            horizontalAlignment: marquee.horizontalAlignment
            verticalAlignment: Text.AlignVCenter
            textFormat: Text.PlainText
        }

        SequentialAnimation {
            running: marquee.running
                     && marquee.visible
                     && marqueeLabel.implicitWidth > marquee.width
            loops: Animation.Infinite
            PauseAnimation { duration: 1100 }
            NumberAnimation {
                target: marqueeLabel
                property: "x"
                from: 0
                to: Math.min(0, marquee.width - marqueeLabel.implicitWidth - 10)
                duration: Math.max(
                    1400,
                    (marqueeLabel.implicitWidth - marquee.width) * 30
                )
                easing.type: Easing.Linear
            }
            PauseAnimation { duration: 900 }
            PropertyAction { target: marqueeLabel; property: "x"; value: 0 }
        }
    }

    component MusicButton: Basic.Button {
        id: musicButton
        property color fillColor: "#1578d3"
        property color pressedColor: Qt.darker(fillColor, 1.12)
        property color textColor: "white"
        property color outlineColor: "transparent"

        height: 54
        scale: down ? 0.96 : 1.0
        opacity: enabled ? 1.0 : 0.42
        Behavior on scale { NumberAnimation { duration: 80 } }

        background: Rectangle {
            radius: 13
            color: musicButton.down
                   ? musicButton.pressedColor : musicButton.fillColor
            border.color: musicButton.outlineColor
            border.width: musicButton.outlineColor === "transparent" ? 0 : 2
        }

        contentItem: Text {
            text: musicButton.text
            color: musicButton.textColor
            font.pixelSize: 11
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    component BrowseChip: Basic.Button {
        id: browseChip
        required property string mode
        property bool active: musicView.viewModel.activeChip === mode

        width: 78
        height: 29
        scale: down ? 0.96 : 1.0
        onClicked: musicView.browse(mode)

        background: Rectangle {
            radius: 16
            color: browseChip.active ? "#102a5e" : "#e5f6f8"
            border.color: browseChip.active ? "#102a5e" : "#8fd4d9"
            border.width: 2
        }

        contentItem: Text {
            id: chipText
            text: browseChip.text
            color: browseChip.active ? "white" : "#365d72"
            font.pixelSize: 10
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#eaf9ff" }
            GradientStop { position: 0.62; color: "#eef8ff" }
            GradientStop { position: 1.0; color: "#fff5dc" }
        }
    }

    Row {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 10

        Rectangle {
            id: browserPanel
            objectName: "musicSongPanel"
            width: 354
            height: parent.height
            radius: 16
            color: "#fbfeff"
            border.color: "#9bd7e5"
            border.width: 2

            Grid {
                id: chipStrip
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: 7
                columns: 4
                columnSpacing: 6
                rowSpacing: 5

                BrowseChip { mode: "albums"; text: "ALBUMS" }
                BrowseChip { mode: "artists"; text: "ARTISTS" }
                BrowseChip { mode: "series"; text: "SERIES" }
                BrowseChip { mode: "songs"; text: "SONGS" }
                BrowseChip { mode: "recent"; text: "RECENT" }
                BrowseChip { mode: "most"; text: "MOST" }
                BrowseChip { mode: "favorites"; text: "FAVORITES" }
                BrowseChip { mode: "playlists"; text: "PLAYLISTS" }
            }

            Rectangle {
                id: browserHeader
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.topMargin: 75
                height: 42
                color: "#dff6f5"

                MarqueeText {
                    anchors.left: parent.left
                    anchors.leftMargin: 13
                    anchors.right: headerAction.left
                    anchors.rightMargin: 7
                    anchors.verticalCenter: parent.verticalCenter
                    height: 28
                    text: musicView.viewModel.browserTitle || "MUSIC"
                    color: "#102a5e"
                    font.pixelSize: 15
                    font.bold: true
                }

                Basic.Button {
                    id: headerAction
                    anchors.right: parent.right
                    anchors.rightMargin: 7
                    anchors.verticalCenter: parent.verticalCenter
                    width: visible ? 84 : 0
                    height: 29
                    visible: musicView.viewModel.browserKind === "tracks"
                             && ["albums", "artists", "series"].indexOf(
                                 musicView.viewModel.activeChip
                             ) >= 0
                    text: "ALL " + String(musicView.viewModel.activeChip || "").toUpperCase()
                    onClicked: musicView.browse(musicView.viewModel.activeChip)
                }
            }

            ListView {
                id: songList
                objectName: "musicSongList"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: browserHeader.bottom
                anchors.bottom: playlistCreator.visible
                                ? playlistCreator.top : parent.bottom
                anchors.margins: 8
                spacing: 6
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                interactive: contentHeight > height
                model: browserModel

                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    width: 10
                }

                delegate: Rectangle {
                    required property var model
                    required property int index
                    width: ListView.view.width
                    height: 57
                    radius: 12
                    property bool isTrack: model.kind === "track"
                    property bool selected: isTrack
                            && model.trackIndex
                               === musicView.viewModel.selectedIndex
                    property bool playing: isTrack
                            && model.trackIndex
                               === musicView.viewModel.playingIndex
                            && ["playing", "paused"].indexOf(
                                musicView.viewModel.state
                            ) >= 0
                    color: selected ? "#d7f1ff"
                          : index % 3 === 0 ? "#f3fcfb"
                          : index % 3 === 1 ? "#fffaf0" : "#fff4f7"
                    border.color: playing ? "#1578d3"
                                  : selected ? "#67b8dc"
                                  : index % 3 === 0 ? "#9edfd9"
                                  : index % 3 === 1 ? "#efd67d" : "#efafbf"
                    border.width: playing ? 3 : 2

                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 7
                        radius: 3
                        color: playing ? "#1578d3"
                              : index % 3 === 0 ? "#41aaa5"
                              : index % 3 === 1 ? "#d7a91f" : "#dd718e"
                    }

                    Column {
                        anchors.left: parent.left
                        anchors.leftMargin: 17
                        anchors.right: rowBadge.left
                        anchors.rightMargin: 7
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 1

                        MarqueeText {
                            width: parent.width
                            height: 23
                            text: model.title || "Untitled song"
                            color: "#102a5e"
                            font.pixelSize: 14
                            font.bold: true
                        }

                        MarqueeText {
                            width: parent.width
                            height: 18
                            text: model.subtitle || model.album || ""
                            color: "#58708c"
                            font.pixelSize: 10
                        }
                    }

                    Rectangle {
                        id: rowBadge
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        width: playing ? 42 : model.kind === "track" ? 12 : 35
                        height: playing ? 24 : model.kind === "track" ? 12 : 24
                        radius: height / 2
                        color: playing ? "#1578d3"
                              : model.kind === "track" ? "transparent" : "#e1eff7"

                        Text {
                            anchors.centerIn: parent
                            text: playing
                                  ? musicView.viewModel.state === "paused" ? "II" : "PLAY"
                                  : model.kind === "track" ? "" : ">"
                            color: playing ? "white" : "#365d72"
                            font.pixelSize: 9
                            font.bold: true
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            if (model.kind === "track") {
                                musicView.send(
                                    "music_select",
                                    model.trackIndex
                                )
                            } else if (model.kind === "group") {
                                musicView.resetListOnNextSync = true
                                musicView.send(
                                    "music_open_group",
                                    JSON.stringify({
                                        kind: model.groupKind,
                                        value: model.key
                                    })
                                )
                            } else if (model.kind === "playlist") {
                                musicView.resetListOnNextSync = true
                                musicView.send("music_open_playlist", model.key)
                            }
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    width: parent.width - 34
                    visible: songList.count === 0
                    text: musicView.viewModel.browserKind === "playlists"
                          ? "Create a playlist below!"
                          : "Nothing is in this collection yet."
                    color: "#58708c"
                    font.pixelSize: 15
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                }
            }

            Rectangle {
                id: playlistCreator
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 8
                height: 42
                radius: 11
                color: "#edf7ff"
                visible: musicView.viewModel.browserKind === "playlists"

                TextField {
                    id: playlistName
                    anchors.left: parent.left
                    anchors.top: parent.top
                    width: parent.width - 92
                    height: parent.height
                    placeholderText: "New playlist name"
                    maximumLength: 32
                    font.pixelSize: 13
                }

                MusicButton {
                    anchors.right: parent.right
                    width: 86
                    height: parent.height
                    text: "CREATE"
                    enabled: playlistName.text.trim().length > 0
                             && musicView.viewModel.libraryReadOnly !== true
                    onClicked: {
                        musicView.resetListOnNextSync = true
                        musicView.send("music_create_playlist", playlistName.text)
                        playlistName.clear()
                    }
                }
            }
        }

        Column {
            width: parent.width - browserPanel.width - 10
            height: parent.height
            spacing: 7

            Rectangle {
                objectName: "musicNowPlayingCard"
                width: parent.width
                height: 326
                radius: 16
                color: "#fbfeff"
                border.color: "#acdbe5"
                border.width: 2

                Rectangle {
                    id: artFrame
                    objectName: "musicAlbumArtFrame"
                    x: 13
                    y: 13
                    width: 186
                    height: 186
                    radius: 15
                    color: "#dff6f5"
                    border.color: "#67c6bd"
                    border.width: 3
                    clip: true

                    Text {
                        anchors.centerIn: parent
                        text: "MUSIC"
                        color: "#187a85"
                        font.pixelSize: 22
                        font.bold: true
                    }

                    Image {
                        id: albumArt
                        objectName: "musicAlbumArt"
                        anchors.centerIn: parent
                        property real sourceRatio: sourceSize.height > 0
                                ? sourceSize.width / sourceSize.height : 1
                        width: sourceRatio >= 1
                               ? parent.width : parent.height * sourceRatio
                        height: sourceRatio >= 1
                                ? parent.width / sourceRatio : parent.height
                        source: musicView.viewModel.artworkSource || ""
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        cache: true
                    }
                }

                Column {
                    anchors.left: artFrame.right
                    anchors.leftMargin: 13
                    anchors.right: parent.right
                    anchors.rightMargin: 13
                    y: 14
                    spacing: 5

                    Rectangle {
                        width: Math.min(parent.width, 118)
                        height: 24
                        radius: 12
                        color: musicView.viewModel.state === "playing" ? "#d9f5f2"
                              : musicView.viewModel.state === "paused" ? "#fff0b8"
                              : "#eaf5ff"

                        Text {
                            anchors.centerIn: parent
                            text: musicView.viewModel.state === "playing" ? "NOW PLAYING"
                                  : musicView.viewModel.state === "paused" ? "PAUSED"
                                  : "READY"
                            color: "#365d72"
                            font.pixelSize: 10
                            font.bold: true
                        }
                    }

                    MarqueeText {
                        width: parent.width
                        height: 34
                        text: musicView.viewModel.title || "Music Time!"
                        color: "#102a5e"
                        font.pixelSize: 21
                        font.bold: true
                    }

                    MarqueeText {
                        width: parent.width
                        height: 23
                        text: musicView.viewModel.album || "Unknown Album"
                        color: "#1578d3"
                        font.pixelSize: 13
                        font.bold: true
                    }

                    MarqueeText {
                        width: parent.width
                        height: 20
                        visible: text !== ""
                        text: musicView.viewModel.artist || ""
                        color: "#58708c"
                        font.pixelSize: 11
                    }

                    MarqueeText {
                        width: parent.width
                        height: 20
                        visible: text !== ""
                        text: musicView.viewModel.series || ""
                        color: "#7656a7"
                        font.pixelSize: 11
                        font.bold: true
                    }

                    Row {
                        spacing: 6

                        MusicButton {
                            width: 76
                            height: 32
                            text: musicView.viewModel.favorite ? "★ FAVE" : "☆ FAVE"
                            fillColor: musicView.viewModel.favorite ? "#d7a91f" : "#7656a7"
                            enabled: musicView.viewModel.canPlay === true
                                     && musicView.viewModel.libraryReadOnly !== true
                            onClicked: musicView.send("music_favorite")
                        }

                        MusicButton {
                            width: 109
                            height: 32
                            visible: musicView.viewModel.activePlaylist !== ""
                            text: musicView.viewModel.playlistContainsCurrent
                                  ? "REMOVE"
                                  : "ADD: " + String(
                                      musicView.viewModel.activePlaylist
                                  ).toUpperCase()
                            fillColor: "#187a85"
                            enabled: musicView.viewModel.canPlay === true
                                     && musicView.viewModel.libraryReadOnly !== true
                            onClicked: musicView.send("music_playlist_track")
                        }
                    }
                }

                Text {
                    x: 14
                    y: 207
                    width: parent.width - 28
                           - (musicView.viewModel.viewingPlaylist === true ? 74 : 0)
                    height: 20
                    text: musicView.viewModel.status || ""
                    color: String(text).indexOf("could") >= 0
                           || String(text).indexOf("read-only") >= 0
                           ? "#b3261e" : "#58708c"
                    font.pixelSize: 11
                    font.bold: true
                    elide: Text.ElideRight
                }

                Basic.Slider {
                    id: progressSlider
                    objectName: "musicProgressSlider"
                    x: 14
                    y: 237
                    width: parent.width - 28
                    height: 34
                    from: 0
                    to: Math.max(1, musicView.viewModel.duration || 0)
                    enabled: musicView.viewModel.canSeek === true

                    Binding {
                        target: progressSlider
                        property: "value"
                        value: musicView.viewModel.position || 0
                        when: !progressSlider.pressed
                    }

                    onPressedChanged: {
                        if (!pressed && enabled)
                            musicView.send("music_seek", value)
                    }

                    background: Rectangle {
                        x: progressSlider.leftPadding
                        y: progressSlider.topPadding
                           + progressSlider.availableHeight / 2 - height / 2
                        width: progressSlider.availableWidth
                        height: 8
                        radius: 4
                        color: "#d3e6ef"

                        Rectangle {
                            width: progressSlider.visualPosition * parent.width
                            height: parent.height
                            radius: 4
                            color: "#1578d3"
                        }
                    }

                    handle: Rectangle {
                        x: progressSlider.leftPadding
                           + progressSlider.visualPosition
                           * (progressSlider.availableWidth - width)
                        y: progressSlider.topPadding
                           + progressSlider.availableHeight / 2 - height / 2
                        width: 22
                        height: 22
                        radius: 11
                        color: progressSlider.pressed ? "#f2c84b" : "white"
                        border.color: "#1578d3"
                        border.width: 3
                    }
                }

                Text {
                    x: 14
                    y: 284
                    text: musicView.viewModel.positionLabel || "0:00"
                    color: "#365d72"
                    font.pixelSize: 11
                    font.bold: true
                }

                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 14
                    y: 284
                    text: musicView.viewModel.durationLabel || "0:00"
                    color: "#365d72"
                    font.pixelSize: 11
                    font.bold: true
                }

                MusicButton {
                    anchors.right: parent.right
                    anchors.rightMargin: 13
                    y: 201
                    width: 66
                    height: 29
                    visible: musicView.viewModel.viewingPlaylist === true
                    text: "DELETE LIST"
                    fillColor: "#c84b5b"
                    enabled: musicView.viewModel.libraryReadOnly !== true
                    onClicked: {
                        musicView.resetListOnNextSync = true
                        musicView.send("music_delete_playlist")
                    }
                }
            }

            Row {
                width: parent.width
                spacing: 6

                MusicButton {
                    width: (parent.width - 24) / 5
                    text: "PLAY"
                    enabled: musicView.viewModel.canPlay === true
                    fillColor: "#3b8e63"
                    onClicked: musicView.send("music_play")
                }

                MusicButton {
                    width: (parent.width - 24) / 5
                    text: musicView.viewModel.state === "paused" ? "RESUME" : "PAUSE"
                    enabled: musicView.viewModel.canPause === true
                    fillColor: "#1578d3"
                    onClicked: musicView.send("music_pause")
                }

                MusicButton {
                    width: (parent.width - 24) / 5
                    text: "STOP"
                    enabled: musicView.viewModel.canPause === true
                    fillColor: "#c84b5b"
                    onClicked: musicView.send("music_stop")
                }

                MusicButton {
                    width: (parent.width - 24) / 5
                    text: "REPEAT"
                    fillColor: musicView.viewModel.repeat ? "#d7a91f" : "#7656a7"
                    outlineColor: musicView.viewModel.repeat ? "#fff0b8" : "transparent"
                    onClicked: musicView.send("music_repeat")
                }

                MusicButton {
                    width: (parent.width - 24) / 5
                    text: "SHUFFLE"
                    fillColor: musicView.viewModel.shuffle ? "#d7a91f" : "#187a85"
                    outlineColor: musicView.viewModel.shuffle ? "#fff0b8" : "transparent"
                    enabled: musicView.viewModel.trackCount > 0
                    onClicked: musicView.send("music_shuffle")
                }
            }
        }
    }
}
