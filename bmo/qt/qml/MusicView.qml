import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Basic as Basic

Item {
    id: musicView

    required property var controller
    property var viewModel: controller.viewData

    function send(action, value) {
        controller.requestViewAction(
            action,
            value === undefined ? "" : String(value)
        )
    }

    component MusicButton: Basic.Button {
        id: musicButton
        property color fillColor: "#1578d3"
        property color pressedColor: Qt.darker(fillColor, 1.12)
        property color textColor: "white"
        property color outlineColor: "transparent"

        height: 52
        scale: down ? 0.96 : 1.0
        opacity: enabled ? 1.0 : 0.42

        Behavior on scale { NumberAnimation { duration: 80 } }

        background: Rectangle {
            radius: 14
            color: musicButton.down
                   ? musicButton.pressedColor : musicButton.fillColor
            border.color: musicButton.outlineColor
            border.width: musicButton.outlineColor === "transparent" ? 0 : 2
        }

        contentItem: Text {
            text: musicButton.text
            color: musicButton.textColor
            font.pixelSize: 13
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
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

    Rectangle {
        x: -34; y: 270; width: 112; height: 112; radius: 56
        color: "#5bc9c2"; opacity: 0.10
    }

    Rectangle {
        x: 728; y: 300; width: 104; height: 104; radius: 52
        color: "#f2c84b"; opacity: 0.15
    }

    Row {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 12

        Rectangle {
            id: songPanel
            objectName: "musicSongPanel"
            width: 342
            height: parent.height
            radius: 17
            color: "#fbfeff"
            border.color: "#9bd7e5"
            border.width: 2

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 48
                radius: 15
                color: "#dff6f5"

                Label {
                    anchors.left: parent.left
                    anchors.leftMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    text: "SONGS"
                    color: "#102a5e"
                    font.pixelSize: 18
                    font.bold: true
                    font.letterSpacing: 0.8
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    width: 54
                    height: 28
                    radius: 14
                    color: "#102a5e"

                    Label {
                        anchors.centerIn: parent
                        text: musicView.viewModel.trackCount || 0
                        color: "white"
                        font.pixelSize: 13
                        font.bold: true
                    }
                }
            }

            ListView {
                id: songList
                objectName: "musicSongList"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.topMargin: 56
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 10
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 7
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                interactive: contentHeight > height
                model: musicView.viewModel.tracks || []
                currentIndex: musicView.viewModel.selectedIndex === undefined
                              ? -1 : musicView.viewModel.selectedIndex

                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                    width: 10
                }

                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    width: ListView.view.width
                    height: 59
                    radius: 13
                    color: modelData.selected ? "#d7f1ff"
                          : index % 3 === 0 ? "#f3fcfb"
                          : index % 3 === 1 ? "#fffaf0" : "#fff4f7"
                    border.color: modelData.playing ? "#1578d3"
                                  : modelData.selected ? "#67b8dc"
                                  : index % 3 === 0 ? "#9edfd9"
                                  : index % 3 === 1 ? "#efd67d" : "#efafbf"
                    border.width: modelData.playing ? 3 : 2

                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 7
                        radius: 3
                        color: modelData.playing ? "#1578d3"
                              : index % 3 === 0 ? "#41aaa5"
                              : index % 3 === 1 ? "#d7a91f" : "#dd718e"
                    }

                    Column {
                        anchors.left: parent.left
                        anchors.leftMargin: 17
                        anchors.right: playingBadge.left
                        anchors.rightMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2

                        Label {
                            width: parent.width
                            text: modelData.title || "Untitled song"
                            color: "#102a5e"
                            font.pixelSize: 15
                            font.bold: true
                            elide: Text.ElideRight
                        }

                        Label {
                            width: parent.width
                            text: modelData.album || ""
                            color: "#58708c"
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                    }

                    Rectangle {
                        id: playingBadge
                        anchors.right: parent.right
                        anchors.rightMargin: 9
                        anchors.verticalCenter: parent.verticalCenter
                        width: modelData.playing ? 43 : 12
                        height: modelData.playing ? 25 : 12
                        radius: height / 2
                        color: modelData.playing ? "#1578d3" : "transparent"

                        Label {
                            anchors.centerIn: parent
                            visible: modelData.playing
                            text: musicView.viewModel.state === "paused" ? "II" : "PLAY"
                            color: "white"
                            font.pixelSize: 9
                            font.bold: true
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: musicView.send("music_select", modelData.index)
                    }
                }

                Label {
                    anchors.centerIn: parent
                    width: parent.width - 34
                    visible: songList.count === 0
                    text: "No songs tagged for this music player yet."
                    color: "#58708c"
                    font.pixelSize: 16
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                }
            }
        }

        Column {
            width: parent.width - songPanel.width - 12
            height: parent.height
            spacing: 10

            Rectangle {
                objectName: "musicNowPlayingCard"
                width: parent.width
                height: 303
                radius: 17
                color: "#fbfeff"
                border.color: "#acdbe5"
                border.width: 2

                Rectangle {
                    id: artFrame
                    x: 14
                    anchors.verticalCenter: parent.verticalCenter
                    width: 210
                    height: 210
                    radius: 17
                    color: "#dff6f5"
                    border.color: "#67c6bd"
                    border.width: 3
                    clip: true

                    Rectangle {
                        anchors.fill: parent
                        color: "#dff6f5"

                        Column {
                            anchors.centerIn: parent
                            spacing: 7
                            Label {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: "MUSIC"
                                color: "#187a85"
                                font.pixelSize: 23
                                font.bold: true
                                font.letterSpacing: 1.5
                            }
                            Row {
                                anchors.horizontalCenter: parent.horizontalCenter
                                spacing: 6
                                Repeater {
                                    model: ["#f2c84b", "#f08aa6", "#5bc9c2"]
                                    delegate: Rectangle {
                                        required property string modelData
                                        width: 18; height: 18; radius: 9
                                        color: modelData
                                    }
                                }
                            }
                        }
                    }

                    Image {
                        anchors.fill: parent
                        source: musicView.viewModel.artworkSource || ""
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        cache: true
                    }
                }

                Column {
                    anchors.left: artFrame.right
                    anchors.leftMargin: 16
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 9

                    Rectangle {
                        width: Math.min(parent.width, 126)
                        height: 27
                        radius: 13
                        color: musicView.viewModel.state === "playing" ? "#d9f5f2"
                              : musicView.viewModel.state === "paused" ? "#fff0b8"
                              : "#eaf5ff"

                        Label {
                            anchors.centerIn: parent
                            text: musicView.viewModel.state === "playing" ? "NOW PLAYING"
                                  : musicView.viewModel.state === "paused" ? "PAUSED"
                                  : "READY"
                            color: "#365d72"
                            font.pixelSize: 11
                            font.bold: true
                        }
                    }

                    Label {
                        width: parent.width
                        text: musicView.viewModel.title || "Music Time!"
                        color: "#102a5e"
                        font.pixelSize: 22
                        font.bold: true
                        wrapMode: Text.Wrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                    }

                    Label {
                        width: parent.width
                        text: musicView.viewModel.album || ""
                        color: "#1578d3"
                        font.pixelSize: 14
                        font.bold: true
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }

                    Label {
                        width: parent.width
                        visible: text !== ""
                        text: musicView.viewModel.artist || ""
                        color: "#58708c"
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }

                    Label {
                        width: parent.width
                        text: musicView.viewModel.status || ""
                        color: (musicView.viewModel.status || "").indexOf("needs") >= 0
                               ? "#b3261e" : "#58708c"
                        font.pixelSize: 12
                        font.bold: true
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                    }
                }
            }

            Row {
                width: parent.width
                spacing: 8

                MusicButton {
                    width: (parent.width - 24) / 4
                    text: "PLAY"
                    enabled: musicView.viewModel.canPlay === true
                    fillColor: "#3b8e63"
                    onClicked: musicView.send("music_play")
                }

                MusicButton {
                    width: (parent.width - 24) / 4
                    text: musicView.viewModel.state === "paused" ? "RESUME" : "PAUSE"
                    enabled: musicView.viewModel.canPause === true
                    fillColor: "#1578d3"
                    onClicked: musicView.send("music_pause")
                }

                MusicButton {
                    width: (parent.width - 24) / 4
                    text: "STOP"
                    enabled: musicView.viewModel.canPause === true
                    fillColor: "#c84b5b"
                    onClicked: musicView.send("music_stop")
                }

                MusicButton {
                    width: (parent.width - 24) / 4
                    text: "REPEAT"
                    fillColor: musicView.viewModel.repeat === true ? "#d7a91f" : "#7656a7"
                    outlineColor: musicView.viewModel.repeat === true ? "#fff0b8" : "transparent"
                    onClicked: musicView.send("music_repeat")
                }
            }
        }
    }
}
