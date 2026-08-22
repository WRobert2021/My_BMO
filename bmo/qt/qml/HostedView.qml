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

        Label {
            anchors.left: parent.left
            anchors.leftMargin: 22
            anchors.verticalCenter: parent.verticalCenter
            text: controller.viewTitle.toUpperCase()
            color: "white"
            font.pixelSize: 23
            font.bold: true
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
            case "album": return albumView
            case "weather": return weatherView
            case "calendar": return calendarView
            case "twenty_questions": return twentyView
            case "matching_game": return matchingView
            case "learning": return learningView
            case "galaxy_rvr": return galaxyRvrView
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
        id: galaxyRvrView
        Item {
            id: galaxyPage
            property int previewToken: 0
            property bool showFirstPreview: false
            property bool previewActive: root.viewModel.previewEnabled === true
                                         && root.viewModel.rover_connected === true
            function requestPreview() {
                if (!previewActive || root.viewModel.taking_photo === true)
                    return
                let target = showFirstPreview ? previewSecond : previewFirst
                if (target.status === Image.Loading)
                    return
                previewToken += 1
                target.source = root.viewModel.captureUrl + "?t=" + previewToken
            }
            onPreviewActiveChanged: {
                if (!previewActive) {
                    previewFirst.source = ""
                    previewSecond.source = ""
                    showFirstPreview = false
                }
            }

            Timer {
                interval: Math.max(100, root.viewModel.previewIntervalMs || 250)
                running: parent.previewActive
                         && root.viewModel.taking_photo !== true
                repeat: true
                triggeredOnStart: true
                onTriggered: parent.requestPreview()
            }

            Row {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 14

                Rectangle {
                    width: 490
                    height: parent.height
                    radius: 10
                    color: "#102a5e"
                    border.color: "#b7d7e8"

                    Image {
                        id: previewFirst
                        anchors.fill: parent
                        anchors.margins: 8
                        visible: galaxyPage.previewActive
                                 && galaxyPage.showFirstPreview
                                 && status === Image.Ready
                        cache: false
                        asynchronous: true
                        fillMode: Image.PreserveAspectFit
                        onStatusChanged: {
                            if (status === Image.Ready)
                                galaxyPage.showFirstPreview = true
                        }
                    }

                    Image {
                        id: previewSecond
                        anchors.fill: parent
                        anchors.margins: 8
                        visible: galaxyPage.previewActive
                                 && !galaxyPage.showFirstPreview
                                 && status === Image.Ready
                        cache: false
                        asynchronous: true
                        fillMode: Image.PreserveAspectFit
                        onStatusChanged: {
                            if (status === Image.Ready)
                                galaxyPage.showFirstPreview = false
                        }
                    }

                    Column {
                        anchors.centerIn: parent
                        width: parent.width - 40
                        spacing: 10
                        visible: !galaxyPage.previewActive
                                 || (previewFirst.status !== Image.Ready
                                     && previewSecond.status !== Image.Ready)
                        Label {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            text: galaxyPage.previewActive
                                  ? "LOADING CAMERA"
                                  : (root.viewModel.rover_connected === true
                                     ? "CAMERA PREVIEW DISABLED"
                                     : "WAITING FOR GALAXYRVR")
                            color: "white"
                            font.pixelSize: 21
                            font.bold: true
                        }
                        Label {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                            text: "Configured rover: " + (root.viewModel.host || "")
                            color: "#bde7ff"
                            font.pixelSize: 15
                        }
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.margins: 8
                        height: 52
                        radius: 6
                        color: "#cc102a5e"
                        Label {
                            anchors.centerIn: parent
                            text: "MOTORS  "
                                  + (root.viewModel.left_power || 0)
                                  + " / "
                                  + (root.viewModel.right_power || 0)
                                  + "     CAMERA  "
                                  + (root.viewModel.servo_angle || 0)
                                  + "°\n"
                                  + (root.viewModel.axis_summary || "")
                            color: "white"
                            font.pixelSize: 13
                            font.bold: true
                        }
                    }
                }

                Column {
                    width: parent.width - 504
                    spacing: 8

                    Label {
                        width: parent.width
                        wrapMode: Text.Wrap
                        text: root.viewModel.state || "Starting remote..."
                        color: "#102a5e"
                        font.pixelSize: 18
                        font.bold: true
                    }
                    Label {
                        width: parent.width
                        wrapMode: Text.Wrap
                        visible: (root.viewModel.error || "") !== ""
                        text: root.viewModel.error || ""
                        color: "#b3261e"
                        font.pixelSize: 13
                    }
                    Repeater {
                        model: root.viewModel.controls || []
                        delegate: Label {
                            required property string modelData
                            width: 260
                            wrapMode: Text.Wrap
                            text: "• " + modelData
                            color: "#58708c"
                            font.pixelSize: 14
                        }
                    }
                    Button {
                        width: parent.width
                        height: 48
                        text: root.viewModel.taking_photo ? "SAVING..." : "SNAP PHOTO (A)"
                        enabled: root.viewModel.taking_photo !== true
                                 && root.viewModel.rover_connected === true
                        onClicked: root.send("galaxy_rvr_snapshot")
                    }
                    Label {
                        width: parent.width
                        elide: Text.ElideMiddle
                        visible: (root.viewModel.last_photo || "") !== ""
                        text: "Saved: " + (root.viewModel.last_photo || "")
                        color: "#3b8e63"
                        font.pixelSize: 12
                    }
                }
            }
        }
    }

    Component {
        id: timerView
        Item {
            Column {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 10
                Row {
                    width: parent.width
                    spacing: 12
                    Label {
                        width: parent.width - 170
                        text: (root.viewModel.items || []).length + " active"
                        color: "#58708c"
                        font.pixelSize: 18
                        font.bold: true
                    }
                    Button {
                        width: 150
                        height: 46
                        text: root.viewModel.adding ? "CANCEL" : "+ NEW TIMER"
                        onClicked: root.send(root.viewModel.adding ? "timer_cancel_add" : "timer_add")
                    }
                }
                Row {
                    visible: root.viewModel.adding === true
                    spacing: 8
                    Repeater {
                        model: ["hours", "minutes", "seconds"]
                        delegate: Column {
                            required property string modelData
                            width: 126
                            spacing: 2
                            Label {
                                width: parent.width
                                horizontalAlignment: Text.AlignHCenter
                                text: modelData.toUpperCase()
                                color: "#58708c"
                            }
                            Row {
                                spacing: 3
                                Button { width: 36; height: 42; text: "−"; onClicked: root.send("timer_adjust", JSON.stringify({field: modelData, amount: -1})) }
                                Label { width: 48; height: 42; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter; text: root.viewModel[modelData] || 0; font.pixelSize: 22; font.bold: true; color: "#102a5e" }
                                Button { width: 36; height: 42; text: "+"; onClicked: root.send("timer_adjust", JSON.stringify({field: modelData, amount: 1})) }
                            }
                        }
                    }
                    Button { width: 148; height: 70; text: "START"; onClicked: root.send("timer_create") }
                }
                MessageText { text: root.viewModel.error || ""; visible: text !== "" }
                ListView {
                    width: parent.width
                    height: parent.height - y
                    spacing: 8
                    clip: true
                    model: root.viewModel.items || []
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width
                        height: 64
                        radius: 10
                        color: "white"
                        border.color: "#b7d7e8"
                        Label { anchors.left: parent.left; anchors.leftMargin: 18; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; color: "#102a5e"; font.pixelSize: 18; font.bold: true }
                        Label { anchors.right: cancel.left; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter; text: modelData.remaining; color: "#1578d3"; font.pixelSize: 24; font.bold: true }
                        Button { id: cancel; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; width: 105; height: 46; text: "CANCEL"; onClicked: root.send("timer_cancel", modelData.id) }
                    }
                }
            }
        }
    }

    Component {
        id: albumView
        Item {
            Column {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8
                Row {
                    width: parent.width
                    spacing: 10
                    Label { width: parent.width - 320; text: (root.viewModel.photoCount || 0) + " photos"; color: "#58708c"; font.pixelSize: 17; font.bold: true }
                    Button { width: 90; height: 42; text: "◀"; enabled: !root.viewModel.detail; onClicked: root.send("album_previous") }
                    Label { width: 90; height: 42; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter; text: root.viewModel.pageLabel || ""; color: "#102a5e"; font.bold: true }
                    Button { width: 90; height: 42; text: "▶"; enabled: !root.viewModel.detail; onClicked: root.send("album_next") }
                }
                MessageText { text: root.viewModel.error || ""; visible: text !== "" }
                Item {
                    width: parent.width
                    height: parent.height - y
                    visible: root.viewModel.detail === true
                    Image { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: parent.width - 210; source: root.viewModel.selectedSource || ""; fillMode: Image.PreserveAspectFit }
                    Column {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: 190
                        spacing: 12
                        Button { width: parent.width; height: 52; text: "BACK TO PHOTOS"; onClicked: root.send("album_back") }
                        Button { width: parent.width; height: 52; text: root.viewModel.busy ? "BMO IS LOOKING..." : "ASK BMO"; enabled: !root.viewModel.busy; onClicked: root.send("album_vision") }
                        Button { width: parent.width; height: 52; text: "DELETE"; onClicked: root.send("album_delete") }
                    }
                }
                GridLayout {
                    visible: root.viewModel.detail !== true
                    width: parent.width
                    columns: 3
                    rowSpacing: 8
                    columnSpacing: 8
                    Repeater {
                        model: root.viewModel.photos || []
                        delegate: Rectangle {
                            required property var modelData
                            Layout.preferredWidth: 246
                            Layout.preferredHeight: 136
                            color: "white"
                            border.color: "#b7d7e8"
                            radius: 8
                            Image { anchors.fill: parent; anchors.margins: 5; source: modelData.source; fillMode: Image.PreserveAspectCrop }
                            MouseArea { anchors.fill: parent; onClicked: root.send("album_select", modelData.path) }
                        }
                    }
                }
            }
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
        Item {
            Column {
                anchors.fill: parent; anchors.margins: 14; spacing: 10
                MessageText { text: root.viewModel.error || ""; visible: text !== "" }
                Column {
                    visible: root.viewModel.screen === "profiles"
                    width: parent.width; spacing: 10
                    Label { text: "Who is learning today?"; color: "#102a5e"; font.pixelSize: 27; font.bold: true }
                    Flow { width: parent.width; spacing: 10; Repeater { model: root.viewModel.profiles || []; delegate: Button { required property var modelData; width: 220; height: 60; text: modelData.label; onClicked: root.send("learning_profile", modelData.id) } } }
                    Button { width: 220; height: 52; text: "TEACHER AREA"; onClicked: root.send("learning_teacher") }
                }
                Column {
                    visible: root.viewModel.screen === "teacher_pin"
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 420; spacing: 8
                    Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: "Enter the 4-digit teacher PIN"; color: "#102a5e"; font.pixelSize: 24; font.bold: true }
                    Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.viewModel.teacherPin || "○ ○ ○ ○"; color: "#1578d3"; font.pixelSize: 25; font.bold: true }
                    GridLayout {
                        anchors.horizontalCenter: parent.horizontalCenter; columns: 3; rowSpacing: 5; columnSpacing: 5
                        Repeater { model: ["1","2","3","4","5","6","7","8","9"]; delegate: Button { required property string modelData; Layout.preferredWidth: 82; Layout.preferredHeight: 48; text: modelData; onClicked: root.send("learning_teacher_digit", modelData) } }
                        Button { Layout.preferredWidth: 82; Layout.preferredHeight: 48; text: "CLEAR"; onClicked: root.send("learning_teacher_clear") }
                        Button { Layout.preferredWidth: 82; Layout.preferredHeight: 48; text: "0"; onClicked: root.send("learning_teacher_digit", "0") }
                        Button { Layout.preferredWidth: 82; Layout.preferredHeight: 48; text: "BACK"; onClicked: root.send("learning_home") }
                    }
                }
                Column {
                    visible: root.viewModel.screen === "teacher_home"
                    width: parent.width; spacing: 9
                    Label { text: "Teacher area — learner profiles"; color: "#102a5e"; font.pixelSize: 25; font.bold: true }
                    Flow { width: parent.width; spacing: 8; Repeater { model: root.viewModel.teacherProfiles || []; delegate: Button { required property var modelData; width: 220; height: 56; text: modelData.label + (modelData.archived ? " (archived)" : ""); onClicked: root.send("learning_teacher_profile", modelData.id) } } }
                    Row { spacing: 8; TextField { id: newTeacherLearner; width: 360; height: 48; placeholderText: "New learner name" } Button { width: 170; height: 48; text: "ADD LEARNER"; enabled: !root.viewModel.readOnly; onClicked: { root.send("learning_create_profile", newTeacherLearner.text); newTeacherLearner.clear() } } }
                    Button { width: 150; height: 44; text: "EXIT TEACHER"; onClicked: root.send("learning_home") }
                }
                Column {
                    visible: root.viewModel.screen === "teacher_profile"
                    width: parent.width; spacing: 8
                    Label { text: "Learner: " + (root.viewModel.teacherProfileName || ""); color: "#102a5e"; font.pixelSize: 24; font.bold: true }
                    Row { spacing: 8; TextField { id: renameTeacherLearner; width: 330; height: 46; placeholderText: "Rename learner" } Button { width: 150; height: 46; text: "RENAME"; enabled: !root.viewModel.readOnly; onClicked: { root.send("learning_rename_profile", renameTeacherLearner.text); renameTeacherLearner.clear() } } Button { width: 150; height: 46; text: "REPORT"; onClicked: root.send("learning_teacher_report") } }
                    Flow { width: parent.width; spacing: 8; Repeater { model: root.viewModel.teacherPlans || []; delegate: Button { required property var modelData; width: 230; height: 56; text: modelData.label + (modelData.enabled ? "" : " (off)"); onClicked: root.send("learning_teacher_plan", modelData.id) } } }
                    Row { spacing: 8; TextField { id: newLearningPlan; width: 350; height: 46; placeholderText: "New plan name" } Button { width: 170; height: 46; text: "CREATE PLAN"; enabled: !root.viewModel.readOnly; onClicked: { root.send("learning_create_plan", newLearningPlan.text); newLearningPlan.clear() } } Button { width: 120; height: 46; text: "BACK"; onClicked: root.send("learning_teacher_back") } }
                }
                Column {
                    visible: root.viewModel.screen === "teacher_plan"
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 620; spacing: 15
                    Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.viewModel.teacherPlanName || "Learning plan"; color: "#102a5e"; font.pixelSize: 28; font.bold: true }
                    Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: "This plan contains the validated lesson catalog."; color: "#58708c"; font.pixelSize: 16 }
                    Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 12; Button { width: 190; height: 58; text: "ENABLE / DISABLE"; enabled: !root.viewModel.readOnly; onClicked: root.send("learning_toggle_plan") } Button { width: 170; height: 58; text: "VIEW REPORT"; onClicked: root.send("learning_teacher_report") } Button { width: 140; height: 58; text: "BACK"; onClicked: root.send("learning_teacher_back") } }
                }
                Column {
                    visible: root.viewModel.screen === "teacher_report"
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 650; spacing: 16
                    Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: "Progress: " + ((root.viewModel.report || {}).title || ""); color: "#102a5e"; font.pixelSize: 26; font.bold: true }
                    Row { anchors.horizontalCenter: parent.horizontalCenter; spacing: 10; Repeater { model: [{label:"GRADE", value:(root.viewModel.report || {}).grade || "0%"}, {label:"COMPLETE", value:(root.viewModel.report || {}).completion || "0%"}, {label:"ATTEMPTS", value:(root.viewModel.report || {}).attempts || 0}, {label:"RECENT", value:(root.viewModel.report || {}).recent || "0%"}]; delegate: Rectangle { required property var modelData; width: 145; height: 100; radius: 10; color: "white"; border.color: "#91b7c7"; Label { anchors.horizontalCenter: parent.horizontalCenter; y: 15; text: modelData.label; color: "#58708c"; font.bold: true } Label { anchors.horizontalCenter: parent.horizontalCenter; y: 48; text: modelData.value; color: "#102a5e"; font.pixelSize: 24; font.bold: true } } } }
                    Button { anchors.horizontalCenter: parent.horizontalCenter; width: 160; height: 50; text: "BACK"; onClicked: root.send("learning_teacher_back") }
                }
                Column {
                    visible: root.viewModel.screen === "plans"
                    width: parent.width; spacing: 10
                    Label { text: "Hello, " + (root.viewModel.profileName || "Learner") + "!"; color: "#102a5e"; font.pixelSize: 27; font.bold: true }
                    Flow { width: parent.width; spacing: 10; Repeater { model: root.viewModel.plans || []; delegate: Button { required property var modelData; width: 240; height: 64; text: modelData.label; onClicked: root.send("learning_plan", modelData.id) } } }
                    Button { width: 240; height: 58; text: "QUICK PRACTICE"; onClicked: root.send("learning_quick_start") }
                    Button { width: 150; height: 46; text: "CHANGE LEARNER"; onClicked: root.send("learning_home") }
                }
                Column {
                    visible: root.viewModel.screen === "lesson"
                    width: parent.width; spacing: 9
                    Row { width: parent.width; Label { width: parent.width - 170; text: root.viewModel.progress || ""; color: "#58708c"; font.bold: true } Button { width: 150; height: 42; text: "REPLAY"; enabled: root.viewModel.canAnnounce === true; onClicked: root.send("learning_replay") } }
                    Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; text: root.viewModel.prompt || ""; color: "#102a5e"; font.pixelSize: 25; font.bold: true }
                    Flow { width: parent.width; spacing: 9; Repeater { model: root.viewModel.choices || []; delegate: Button { required property var modelData; width: 180; height: 60; text: (modelData.order ? modelData.order + ". " : "") + modelData.label + (modelData.assignment ? " → " + modelData.assignment : ""); highlighted: modelData.selected === true || (modelData.assignment || "") !== ""; onClicked: root.send("learning_choice", modelData.id) } } }
                    Button { visible: root.viewModel.requiresSubmit === true; enabled: root.viewModel.submitReady === true; width: 220; height: 54; anchors.horizontalCenter: parent.horizontalCenter; text: "CHECK ANSWER"; onClicked: root.send("learning_submit") }
                    Button { width: 150; height: 44; text: "END LESSON"; onClicked: root.send("learning_back") }
                }
                Column {
                    visible: root.viewModel.screen === "feedback"
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 620; spacing: 22
                    Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; text: root.viewModel.feedback || ""; color: "#102a5e"; font.pixelSize: 28; font.bold: true }
                    Button { anchors.horizontalCenter: parent.horizontalCenter; width: 260; height: 64; text: root.viewModel.tryAgain ? "TRY AGAIN" : "CONTINUE"; onClicked: root.send("learning_continue") }
                }
                Column {
                    visible: root.viewModel.screen === "complete"
                    anchors.horizontalCenter: parent.horizontalCenter; spacing: 22
                    Label { text: "Great practice!"; color: "#198754"; font.pixelSize: 38; font.bold: true }
                    Button { width: 260; height: 60; text: "BACK TO LEARNING"; onClicked: root.send("learning_back") }
                }
            }
        }
    }

    Component {
        id: unknownView
        Item { Label { anchors.centerIn: parent; text: "This view is unavailable."; color: "#102a5e"; font.pixelSize: 24 } }
    }
}
