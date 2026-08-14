import QtQuick
import QtQuick.Controls

ApplicationWindow {
    id: window
    width: 800
    height: 480
    visible: true
    visibility: Window.FullScreen
    color: "black"
    title: "Be More Agent Qt Shell"

    Image {
        id: face
        anchors.fill: parent
        source: bmoUi.frameSource
        fillMode: Image.PreserveAspectCrop
        asynchronous: false
        cache: false
        visible: !bmoUi.menuVisible

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
        visible: !bmoUi.menuVisible && source.toString() !== ""
    }

    MouseArea {
        anchors.fill: parent
        visible: !bmoUi.menuVisible
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
        visible: !bmoUi.menuVisible && bmoUi.hudVisible

        ScrollView {
            anchors.left: parent.left
            anchors.right: exitButton.left
            anchors.top: parent.top
            anchors.bottom: statusBar.top
            anchors.margins: 10

            TextArea {
                text: bmoUi.responseText
                readOnly: true
                wrapMode: TextEdit.Wrap
                color: "white"
                background: Rectangle { color: "transparent" }
            }
        }

        Button {
            id: exitButton
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            width: 124
            height: 48
            text: "Exit Preview"
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
        id: menu
        anchors.fill: parent
        color: "#e7f7ff"
        visible: bmoUi.menuVisible

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
