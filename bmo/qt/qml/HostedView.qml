import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    required property var controller
    property var viewModel: controller.viewData
    color: "#eef8ff"

    function send(action, value) {
        controller.requestViewAction(action, value === undefined ? "" : String(value))
    }

    Rectangle {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 62
        color: "#102a5e"
        visible: controller.viewKind !== "weather"
        z: 5
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#102a5e" }
            GradientStop { position: 0.74; color: "#164b78" }
            GradientStop { position: 1.0; color: "#187a85" }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 2
            color: "#5bc9c2"
            opacity: 0.85
        }

        Rectangle {
            x: 18
            anchors.verticalCenter: parent.verticalCenter
            width: 13
            height: 13
            radius: 6.5
            color: "#f2c84b"
            border.color: "#fff4bf"
            border.width: 2
        }

        Label {
            anchors.left: parent.left
            anchors.leftMargin: 42
            anchors.verticalCenter: parent.verticalCenter
            text: controller.viewTitle.toUpperCase()
            color: "white"
            font.pixelSize: 23
            font.bold: true
            font.letterSpacing: 0.7
        }

        Row {
            x: 612
            y: 26
            spacing: 11

            Repeater {
                model: ["#f2c84b", "#f08aa6", "#5bc9c2"]

                delegate: Rectangle {
                    required property string modelData
                    width: 8
                    height: 8
                    radius: 2
                    rotation: 45
                    color: modelData
                    opacity: 0.90
                }
            }
        }

        Image {
            objectName: "hostedCompactFace"
            x: 684
            y: 5
            width: 108
            height: 65
            source: controller.frameSource
            fillMode: Image.PreserveAspectFit
            cache: false

            MouseArea {
                anchors.fill: parent
                onClicked: controller.requestViewClose()
            }
        }
    }

    Loader {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: controller.viewKind === "weather" ? parent.top : header.bottom
        anchors.bottom: parent.bottom
        sourceComponent: {
            switch (controller.viewKind) {
            case "timer": return timerView
            case "alarm_clock": return alarmClockView
            case "album": return albumView
            case "weather": return weatherView
            case "calendar": return calendarView
            case "twenty_questions": return twentyView
            case "matching_game": return matchingView
            case "learning": return learningView
            case "music": return musicView
            case "galaxy_rvr": return galaxyRvrView
            case "imessage_relay": return imessageRelayView
            default: return unknownView
            }
        }
    }

    component MessageText: Label {
        width: parent ? parent.width : 300
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        color: "#b3261e"
        font.pixelSize: 14
    }

    Component {
        id: imessageRelayView

        IMessageRelayView {
            controller: root.controller
            viewModel: root.viewModel
        }
    }

    Component {
        id: musicView

        MusicView {
            controller: root.controller
        }
    }

    Component {
        id: galaxyRvrView

        GalaxyRVRView {
            controller: root.controller
            viewModel: root.viewModel
        }
    }
    Component {
        id: alarmClockView

        AlarmClockView {
            controller: root.controller
        }
    }

    Component {
        id: timerView

        TimerView {
            controller: root.controller
        }
    }

    Component {
        id: albumView
        AlbumView {
            controller: root.controller
            viewModel: root.viewModel
        }
    }

    Component {
        id: weatherView
        WeatherView {
            controller: root.controller
            viewModel: root.viewModel
        }
    }

    Component {
        id: calendarView
        CalendarView {
            controller: root.controller
            viewModel: root.viewModel
        }
    }

    Component {
        id: twentyView
        Item {
            Row {
                anchors.fill: parent; anchors.margins: 16; spacing: 14
                Column {
                    width: 570; spacing: 12
                    Rectangle {
                        width: parent.width; height: 185; radius: 12; color: "white"; border.color: "#102a5e"; border.width: 2
                        Label { anchors.centerIn: parent; width: parent.width - 45; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; text: root.viewModel.question || ""; color: "#102a5e"; font.pixelSize: 25; font.bold: true }
                    }
                    Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; text: root.viewModel.status || ""; color: "#58708c"; font.pixelSize: 15; font.bold: true }
                    Row {
                        visible: root.viewModel.awaitingReveal !== true && root.viewModel.active === true
                        spacing: 7
                        Repeater {
                            model: root.viewModel.answers || []
                            delegate: Button { required property string modelData; width: 134; height: 58; text: modelData === "unknown" ? "I DON'T KNOW" : modelData.toUpperCase(); onClicked: root.send("twenty_answer", modelData) }
                        }
                    }
                    Row {
                        visible: root.viewModel.awaitingReveal === true
                        spacing: 8
                        TextField { id: revealObject; width: 400; height: 52; placeholderText: "The object was..." }
                        Button { width: 150; height: 52; text: "TEACH BMO"; onClicked: root.send("twenty_reveal", revealObject.text) }
                    }
                    Button { visible: root.viewModel.active !== true; width: 220; height: 54; text: "PLAY AGAIN"; onClicked: root.send("twenty_play_again") }
                }
                Rectangle {
                    width: 180; height: parent.height; radius: 12; color: "#102a5e"
                    Column {
                        anchors.fill: parent; anchors.margins: 14; spacing: 12
                        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: (root.viewModel.candidateCount || 0) + " candidates"; color: "white"; font.bold: true }
                        Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: (root.viewModel.decisionCount || 0) + " decisions"; color: "#bde7ff" }
                        Label { text: "RECENT THINGS"; color: "#bde7ff"; font.bold: true }
                        Repeater { model: root.viewModel.recentThings || []; delegate: Label { required property string modelData; width: 150; elide: Text.ElideRight; text: modelData; color: "white" } }
                    }
                }
            }
        }
    }

    Component {
        id: matchingView
        Item {
            id: matchingPage
            property int cardCount: (root.viewModel.cards || []).length
            property int cardColumns: cardCount <= 16 ? 4
                                      : cardCount <= 20 ? 5
                                      : cardCount <= 24 ? 6 : 7
            property int cardRows: Math.max(1, Math.ceil(cardCount / cardColumns))

            Rectangle {
                anchors.fill: parent
                color: "#e8f8fb"

                Rectangle {
                    x: -30; y: 282; width: 112; height: 112; radius: 56
                    color: "#65cfc6"; opacity: 0.10
                }
                Rectangle {
                    x: 690; y: -34; width: 120; height: 120; radius: 60
                    color: "#f4cf58"; opacity: 0.13
                }
            }

            Row {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 10

                Rectangle {
                    width: 164
                    height: parent.height
                    radius: 16
                    color: "#fbfeff"
                    border.color: "#acdbe5"
                    border.width: 2

                    Column {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 9

                        Label {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            text: "SCORE"
                            color: "#58708c"
                            font.pixelSize: 13
                            font.bold: true
                            font.letterSpacing: 1.2
                        }

                        Row {
                            width: parent.width
                            spacing: 6

                            Repeater {
                                model: [
                                    { label: "YOU", score: root.viewModel.humanScore || 0, color: "#1578d3" },
                                    { label: "BMO", score: root.viewModel.bmoScore || 0, color: "#102a5e" }
                                ]

                                delegate: Rectangle {
                                    required property var modelData
                                    width: 68
                                    height: 62
                                    radius: 11
                                    color: modelData.color

                                    Column {
                                        anchors.centerIn: parent
                                        spacing: 1
                                        Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.label; color: "white"; font.pixelSize: 12; font.bold: true }
                                        Label { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.score; color: "white"; font.pixelSize: 24; font.bold: true }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: 65
                            radius: 11
                            color: "#eaf5ff"
                            border.color: "#bdd9ed"

                            Label {
                                anchors.fill: parent
                                anchors.margins: 7
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                wrapMode: Text.Wrap
                                text: root.viewModel.status || ""
                                color: "#365d72"
                                font.pixelSize: 14
                                font.bold: true
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: 46
                            radius: 11
                            color: newGameTap.pressed ? "#e8b72f" : "#f3ca4d"
                            border.color: "#d9aa26"
                            border.width: 2

                            Label {
                                anchors.fill: parent
                                text: "NEW GAME"
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                color: "#102a5e"
                                font.bold: true
                                font.pixelSize: 14
                            }

                            MouseArea {
                                id: newGameTap
                                anchors.fill: parent
                                onClicked: root.send("matching_restart")
                            }
                        }

                        Label {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            text: "HOW MANY PAIRS?"
                            color: "#58708c"
                            font.pixelSize: 11
                            font.bold: true
                        }

                        Row {
                            width: parent.width
                            spacing: 4

                            Rectangle {
                                width: 44
                                height: 48
                                radius: 11
                                color: decrementPairs.pressed ? "#cce9ee" : "#edf6f8"
                                border.color: "#9dcfd8"
                                border.width: 2
                                opacity: root.viewModel.pairCount > root.viewModel.minPairCount ? 1.0 : 0.45

                                Label {
                                    anchors.fill: parent
                                    text: "−"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    color: "#102a5e"
                                    font.bold: true
                                    font.pixelSize: 26
                                }

                                MouseArea {
                                    id: decrementPairs
                                    anchors.fill: parent
                                    enabled: root.viewModel.pairCount > root.viewModel.minPairCount
                                    onClicked: root.send("matching_pair_delta", -1)
                                }
                            }

                            Rectangle {
                                width: 48
                                height: 48
                                radius: 11
                                color: "#5bc9c2"
                                border.color: "#268f8b"
                                border.width: 2

                                Label {
                                    anchors.fill: parent
                                    text: root.viewModel.pairCount || 0
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    color: "#102a5e"
                                    font.bold: true
                                    font.pixelSize: 20
                                }
                            }

                            Rectangle {
                                width: 44
                                height: 48
                                radius: 11
                                color: incrementPairs.pressed ? "#cce9ee" : "#edf6f8"
                                border.color: "#9dcfd8"
                                border.width: 2
                                opacity: root.viewModel.pairCount < root.viewModel.maxPairCount ? 1.0 : 0.45

                                Label {
                                    anchors.fill: parent
                                    text: "+"
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    color: "#102a5e"
                                    font.bold: true
                                    font.pixelSize: 24
                                }

                                MouseArea {
                                    id: incrementPairs
                                    anchors.fill: parent
                                    enabled: root.viewModel.pairCount < root.viewModel.maxPairCount
                                    onClicked: root.send("matching_pair_delta", 1)
                                }
                            }
                        }

                        Label {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            text: (root.viewModel.moves || 0) + ((root.viewModel.moves || 0) === 1 ? " move" : " moves")
                            color: "#6f8796"
                            font.pixelSize: 12
                        }
                    }
                }

                Rectangle {
                    width: parent.width - 174
                    height: parent.height
                    radius: 16
                    color: "#d8f0f5"
                    border.color: "#acdbe5"
                    border.width: 2

                    Grid {
                        id: cardBoard
                        anchors.centerIn: parent
                        columns: matchingPage.cardColumns
                        rowSpacing: 6
                        columnSpacing: 6
                        property real cardWidth: Math.max(64, Math.floor(Math.min(
                            (parent.width - 24 - (columns - 1) * columnSpacing) / columns,
                            ((parent.height - 20 - (matchingPage.cardRows - 1) * rowSpacing) / matchingPage.cardRows) / 1.38
                        )))
                        property real cardHeight: Math.floor(cardWidth * 1.38)
                        width: columns * cardWidth + (columns - 1) * columnSpacing
                        height: matchingPage.cardRows * cardHeight + (matchingPage.cardRows - 1) * rowSpacing

                        Repeater {
                            model: root.viewModel.cards || []

                            delegate: Rectangle {
                                required property var modelData
                                width: cardBoard.cardWidth
                                height: cardBoard.cardHeight
                                radius: Math.max(7, width * 0.10)
                                color: modelData.revealed ? "#f8d75d" : "#ffffff"
                                border.color: modelData.matched ? "#2b9b67" : "#ffffff"
                                border.width: modelData.matched ? 4 : 2
                                clip: true

                                Image {
                                    anchors.fill: parent
                                    anchors.margins: modelData.revealed ? 5 : 3
                                    source: modelData.revealed ? modelData.source : root.viewModel.cardBackSource
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: false
                                }

                                Rectangle {
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 3
                                    width: Math.min(22, parent.width * 0.28)
                                    height: width
                                    radius: width / 2
                                    color: "#2b9b67"
                                    visible: modelData.matched

                                    Label {
                                        anchors.centerIn: parent
                                        text: "✓"
                                        color: "white"
                                        font.pixelSize: Math.max(11, parent.width * 0.65)
                                        font.bold: true
                                    }
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    enabled: !root.viewModel.locked && !modelData.matched
                                    onClicked: root.send("matching_card", modelData.id)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: learningView
        LearningView {
            controller: root.controller
            viewModel: root.viewModel
        }
    }

    Component {
        id: unknownView
        Item { Label { anchors.centerIn: parent; text: "This view is unavailable."; color: "#102a5e"; font.pixelSize: 24 } }
    }
}
