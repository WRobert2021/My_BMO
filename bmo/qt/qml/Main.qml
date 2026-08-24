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
        objectName: "mainMenu"
        anchors.fill: parent
        color: "#e7f7ff"
        visible: bmoUi.menuVisible && !bmoUi.viewVisible
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#e8fbff" }
            GradientStop { position: 0.62; color: "#e7f7ff" }
            GradientStop { position: 1.0; color: "#fff3d3" }
        }

        Rectangle {
            x: -46
            y: 84
            width: 126
            height: 126
            radius: 63
            color: "#5bc9c2"
            opacity: 0.10
        }

        Rectangle {
            x: 730
            y: 346
            width: 116
            height: 116
            radius: 58
            color: "#f2c84b"
            opacity: 0.16
        }

        Rectangle {
            id: menuHeader
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 62
            color: "#102a5e"
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "#102a5e" }
                GradientStop { position: 0.72; color: "#164b78" }
                GradientStop { position: 1.0; color: "#187a85" }
            }
        }

        Text {
            x: 24
            y: 12
            text: "BMO MENU"
            color: "white"
            font.pixelSize: 25
            font.bold: true
            font.letterSpacing: 0.8
        }

        Text {
            x: 188
            y: 22
            text: "Pick an adventure!"
            color: "#bdeef0"
            font.pixelSize: 15
            font.bold: true
        }

        Row {
            x: 520
            y: 25
            spacing: 13

            Repeater {
                model: ["#f2c84b", "#f08aa6", "#5bc9c2"]

                delegate: Rectangle {
                    required property string modelData
                    width: 9
                    height: 9
                    radius: 2
                    rotation: 45
                    color: modelData
                    opacity: 0.90
                }
            }
        }

        Row {
            x: 25
            y: 48
            spacing: 5

            Repeater {
                model: ["#5bc9c2", "#f2c84b", "#f08aa6"]

                delegate: Rectangle {
                    required property string modelData
                    width: 7
                    height: 7
                    radius: 3.5
                    color: modelData
                }
            }
        }

        Repeater {
            model: bmoUi.menuItems

            delegate: Item {
                required property var modelData
                required property int index
                x: modelData.x
                y: modelData.y
                width: modelData.width
                height: modelData.height

                Rectangle {
                    objectName: "menuIconHalo"
                    anchors.centerIn: parent
                    width: 122
                    height: 122
                    radius: 61
                    color: index % 3 === 0 ? "#5bc9c2"
                          : index % 3 === 1 ? "#f2c84b" : "#f08aa6"
                    opacity: 0.16
                }

                Image {
                    id: menuIcon
                    objectName: "menuIcon"
                    anchors.centerIn: parent
                    width: modelData.iconSize
                    height: modelData.iconSize
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

                Rectangle {
                    objectName: "menuItemLabel"
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 3
                    width: Math.min(parent.width - 8, menuLabel.implicitWidth + 24)
                    height: 25
                    radius: 12
                    color: "#e6102a5e"
                    border.color: "#66ffffff"
                    border.width: 1

                    Text {
                        id: menuLabel
                        anchors.centerIn: parent
                        width: parent.width - 14
                        text: modelData.label
                        color: "white"
                        font.pixelSize: 12
                        font.bold: true
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                    }
                }
            }
        }

        Image {
            objectName: "menuCompactFace"
            x: 684
            y: 5
            width: 108
            height: 65
            source: bmoUi.frameSource
            fillMode: Image.PreserveAspectFit
            cache: false
        }

        Rectangle {
            objectName: "menuPagePill"
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 8
            width: 78
            height: 24
            radius: 12
            color: "#f7fdff"
            border.color: "#9bd7e5"
            border.width: 1
            visible: bmoUi.menuPageLabel !== ""

            Text {
                anchors.centerIn: parent
                text: bmoUi.menuPageLabel
                color: "#365d72"
                font.pixelSize: 12
                font.bold: true
            }
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
