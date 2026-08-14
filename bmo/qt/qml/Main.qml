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
        visible: source.toString() !== ""
    }

    MouseArea {
        anchors.fill: parent
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
        visible: bmoUi.hudVisible

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
