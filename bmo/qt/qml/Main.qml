import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 800
    height: 480
    visible: true
    visibility: Window.FullScreen
    color: "black"
    title: "Be More Agent"

    Image {
        id: face
        anchors.fill: parent
        source: bmoUi.frameSource
        fillMode: Image.PreserveAspectCrop
        asynchronous: false
        cache: false
        visible: !bmoUi.menuVisible && !bmoUi.viewVisible

        Rectangle {
            anchors.fill: parent
            color: "#102a5e"
            visible: face.status === Image.Error || face.source.toString() === ""
        }
    }

    Image {
        anchors.centerIn: parent
        width: 400
        height: 300
        source: bmoUi.overlaySource
        fillMode: Image.PreserveAspectFit
        visible: !bmoUi.menuVisible && !bmoUi.viewVisible && source.toString() !== ""
    }

    MouseArea {
        anchors.fill: parent
        visible: !bmoUi.menuVisible && !bmoUi.viewVisible
        onPressed: function(mouse) {
            bmoUi.facePressed(mouse.x, mouse.y)
        }
        onReleased: function(mouse) {
            bmoUi.faceReleased(mouse.x, mouse.y)
        }
    }

    Rectangle {
        id: hud
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 122
        color: "#d9000000"
        visible: !bmoUi.menuVisible && !bmoUi.viewVisible && bmoUi.hudVisible

        ScrollView {
            anchors.left: parent.left
            anchors.right: exitButton.left
            anchors.top: parent.top
            anchors.bottom: statusBar.top
            anchors.margins: 10

            TextEdit {
                text: bmoUi.responseText
                readOnly: true
                wrapMode: TextEdit.Wrap
                color: "white"
            }
        }

        Button {
            id: exitButton
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            width: 124
            height: 48
            text: "Exit & Save"
            onClicked: bmoUi.requestExit()
        }

        Rectangle {
            id: statusBar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 30
            color: "#2e2e2e"

            Text {
                anchors.centerIn: parent
                text: bmoUi.status
                color: "white"
                font.pixelSize: 16
            }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 62
        color: "#e6000000"
        visible: bmoUi.typedInputVisible && !bmoUi.menuVisible && !bmoUi.viewVisible && !bmoUi.quietHoursVisible
        z: 80
        Row {
            anchors.fill: parent
            anchors.margins: 8
            spacing: 8
            TextField {
                id: typedCommand
                width: parent.width - 130
                height: 46
                placeholderText: "Type a debug command"
                onAccepted: {
                    bmoUi.submitTypedInput(text)
                    clear()
                }
            }
            Button {
                width: 120
                height: 46
                text: "SEND"
                onClicked: {
                    bmoUi.submitTypedInput(typedCommand.text)
                    typedCommand.clear()
                }
            }
        }
    }

    Rectangle {
        id: menu
        anchors.fill: parent
        color: "#e7f7ff"
        visible: bmoUi.menuVisible && !bmoUi.viewVisible

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 62
            color: "#102a5e"
        }

        Text {
            x: 24
            y: 15
            text: "MENU"
            color: "white"
            font.pixelSize: 24
            font.bold: true
        }

        Repeater {
            model: bmoUi.menuItems

            delegate: Item {
                required property var modelData
                x: modelData.x
                y: modelData.y
                width: modelData.width
                height: modelData.height

                Image {
                    id: menuIcon
                    anchors.centerIn: parent
                    width: 88
                    height: 88
                    source: modelData.iconSource
                    fillMode: Image.PreserveAspectFit
                    asynchronous: false

                    Rectangle {
                        anchors.fill: parent
                        color: "#102a5e"
                        visible: menuIcon.status === Image.Error

                        Text {
                            anchors.centerIn: parent
                            text: "?"
                            color: "white"
                            font.pixelSize: 42
                            font.bold: true
                        }
                    }
                }
            }
        }

        Image {
            x: 684
            y: 5
            width: 108
            height: 65
            source: bmoUi.frameSource
            fillMode: Image.PreserveAspectFit
            cache: false
        }

        Text {
            x: 300
            y: 452
            width: 100
            horizontalAlignment: Text.AlignHCenter
            text: bmoUi.menuPageLabel
            color: "#58708c"
            font.pixelSize: 12
            font.bold: true
        }

        Text {
            x: 418
            y: 452
            width: 350
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
            text: bmoUi.menuSelection === "" ? "" : "Selected: " + bmoUi.menuSelection
            color: "#58708c"
            font.pixelSize: 12
            font.bold: true
        }

        MouseArea {
            anchors.fill: parent
            onPressed: function(mouse) {
                bmoUi.menuPressed(mouse.x, mouse.y)
            }
            onReleased: function(mouse) {
                bmoUi.menuReleased(mouse.x, mouse.y)
            }
        }
    }

    HostedView {
        anchors.fill: parent
        visible: bmoUi.viewVisible
        controller: bmoUi
        z: 100
    }

    Button {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 12
        width: 142
        height: 46
        visible: bmoUi.attentionCount > 0 && !bmoUi.menuVisible && !bmoUi.viewVisible
        text: (bmoUi.attentionLabel || "ITEMS") + "  " + bmoUi.attentionCount
        z: 90
        onClicked: bmoUi.requestAttention()
    }

    Rectangle {
        anchors.fill: parent
        visible: bmoUi.quietHoursVisible
        color: "#0b1d3a"
        z: 200

        Column {
            x: 38
            y: 34
            width: 360
            spacing: 16
            Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: "☾"; color: "#f6e9a8"; font.pixelSize: 72 }
            Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: "BMO IS SLEEPING"; color: "white"; font.pixelSize: 27; font.bold: true }
            Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; text: "Quiet hours are active. A parent can unlock the kiosk."; color: "#a9c2e5"; font.pixelSize: 16 }
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 310; height: 170; radius: 20; color: "#59c7bb"; border.color: "white"; border.width: 4
                Label { x: 42; y: 34; text: "⌒"; color: "#102a52"; font.pixelSize: 55; font.bold: true }
                Label { x: 190; y: 34; text: "⌒"; color: "#102a52"; font.pixelSize: 55; font.bold: true }
                Label { anchors.horizontalCenter: parent.horizontalCenter; y: 93; text: "⌣"; color: "#102a52"; font.pixelSize: 48; font.bold: true }
                Label { anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12; text: "Z z"; color: "white"; font.pixelSize: 22; font.bold: true }
            }
        }

        Column {
            x: 438
            y: 50
            width: 330
            spacing: 10
            Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: "PARENT PIN"; color: "white"; font.pixelSize: 18; font.bold: true }
            Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: bmoUi.quietPinDisplay; color: bmoUi.quietPinError ? "#ef6b72" : "#f6e9a8"; font.pixelSize: 24; font.bold: true }
            GridLayout {
                anchors.horizontalCenter: parent.horizontalCenter
                columns: 3; rowSpacing: 7; columnSpacing: 7
                Repeater { model: ["1","2","3","4","5","6","7","8","9"]; delegate: Button { required property string modelData; Layout.preferredWidth: 82; Layout.preferredHeight: 55; text: modelData; onClicked: bmoUi.quietPinDigit(modelData) } }
                Button { Layout.preferredWidth: 82; Layout.preferredHeight: 55; text: "CLEAR"; onClicked: bmoUi.quietPinClear() }
                Button { Layout.preferredWidth: 82; Layout.preferredHeight: 55; text: "0"; onClicked: bmoUi.quietPinDigit("0") }
                Button { Layout.preferredWidth: 82; Layout.preferredHeight: 55; text: "⌫"; onClicked: bmoUi.quietPinBackspace() }
            }
            Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; text: bmoUi.quietPinError ? "That PIN did not match." : "The unlock lasts until this quiet period ends."; color: bmoUi.quietPinError ? "#ef6b72" : "#a9c2e5"; font.pixelSize: 13 }
        }
    }

    Shortcut {
        sequence: "Escape"
        onActivated: bmoUi.requestExit()
    }
    Shortcut {
        sequence: "Return"
        onActivated: bmoUi.requestPushToTalk()
    }
    Shortcut {
        sequence: "Space"
        onActivated: bmoUi.requestInterrupt()
    }
}
