import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

Item {
    id: root
    required property var controller
    required property var viewModel
    property var displayedMessages: []
    property string displayedMessagesJson: ""

    function reactionIcon(kind) {
        const icons = {
            "heart": "assets/imessage_reactions/heart.svg",
            "thumbs_up": "assets/imessage_reactions/thumbs-up.svg",
            "thumbs_down": "assets/imessage_reactions/thumbs-down.svg",
            "haha": "assets/imessage_reactions/haha.svg",
            "emphasize": "assets/imessage_reactions/emphasize.svg",
            "question": "assets/imessage_reactions/question.svg",
            "unknown": "assets/imessage_reactions/unknown.svg"
        }
        return Qt.resolvedUrl(icons[kind] || icons.unknown)
    }

    function send(action, value) {
        controller.requestViewAction(action, value === undefined ? "" : String(value))
    }

    function syncMessages() {
        let nextMessages = viewModel.messages || []
        let serialized = JSON.stringify(nextMessages)
        if (serialized === displayedMessagesJson)
            return

        let previousY = messageList.contentY
        let preservePosition = displayedMessagesJson !== "" && !messageList.atYBeginning
        displayedMessagesJson = serialized
        displayedMessages = nextMessages
        if (preservePosition) {
            Qt.callLater(function() {
                let minimumY = messageList.originY
                let maximumY = Math.max(
                    minimumY,
                    minimumY + messageList.contentHeight - messageList.height
                )
                messageList.contentY = Math.max(
                    minimumY,
                    Math.min(previousY, maximumY)
                )
            })
        }
    }

    function syncMedia() {
        let selected = viewModel.selectedAttachment || {}
        let category = selected.mediaCategory || ""
        let nextSource = selected.source || ""
        if ((category === "video" || category === "audio") && nextSource !== "") {
            if (String(mediaPlayer.source) !== String(nextSource)) {
                mediaPlayer.stop()
                mediaPlayer.source = nextSource
                mediaPlayer.play()
            }
        } else {
            mediaPlayer.stop()
            mediaPlayer.source = ""
        }
    }

    onViewModelChanged: {
        syncMessages()
        Qt.callLater(syncMedia)
    }
    Component.onCompleted: {
        syncMessages()
        Qt.callLater(syncMedia)
    }
    Component.onDestruction: mediaPlayer.stop()

    AudioOutput {
        id: mediaAudio
        volume: 1.0
    }

    MediaPlayer {
        id: mediaPlayer
        objectName: "relayMediaPlayer"
        audioOutput: mediaAudio
        videoOutput: videoOutput
    }

    Timer {
        interval: 2000
        running: true
        repeat: true
        onTriggered: send("relay_refresh")
    }

    Rectangle {
        anchors.fill: parent
        color: "#e8f8fb"
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 16
        radius: 14
        color: "white"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 6

            ListView {
                id: messageList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 5
                model: root.displayedMessages

                delegate: Rectangle {
                    id: messageCard
                    required property var modelData
                    property var attachmentItems: modelData.attachments || []
                    property bool hasMessageText: String(modelData.text || "").length > 0
                    width: ListView.view.width
                    height: Math.max(58, messageContent.implicitHeight + 14)
                    radius: 8
                    color: "#eef8ff"

                    Column {
                        id: messageContent
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.right: reactionBadges.visible ? reactionBadges.left : parent.right
                        anchors.margins: 7
                        anchors.rightMargin: reactionBadges.visible ? 5 : 7
                        spacing: 3

                        Label {
                            width: parent.width
                            text: messageCard.modelData.sender || "Unknown sender"
                            color: "#102a5e"
                            font.bold: true
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }

                        Label {
                            width: parent.width
                            visible: messageCard.hasMessageText
                            text: messageCard.modelData.text || ""
                            color: "#334d68"
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }

                        Repeater {
                            model: messageCard.attachmentItems

                            delegate: Item {
                                id: attachmentPreview
                                required property var modelData
                                width: messageContent.width
                                height: modelData.media_category === "audio" ? 48 : 104

                                Rectangle {
                                    id: previewTile
                                    width: attachmentPreview.modelData.media_category === "audio"
                                        ? Math.min(parent.width, 340)
                                        : Math.min(parent.width, 164)
                                    height: parent.height
                                    radius: 10
                                    clip: true
                                    color: attachmentPreview.modelData.available === true
                                        ? "#164b78"
                                        : "#e8edf2"
                                    border.width: 2
                                    border.color: attachmentPreview.modelData.available === true
                                        ? "#5bc9c2"
                                        : "#b5c0ca"

                                    Image {
                                        id: photoThumbnail
                                        objectName: "relayPhotoThumbnail"
                                        anchors.fill: parent
                                        visible: attachmentPreview.modelData.available === true
                                                 && attachmentPreview.modelData.media_category === "photo"
                                        source: visible
                                            ? (attachmentPreview.modelData.source || "")
                                            : ""
                                        sourceSize.width: 328
                                        sourceSize.height: 208
                                        fillMode: Image.PreserveAspectCrop
                                        asynchronous: true
                                    }

                                    Item {
                                        id: videoThumbnail
                                        objectName: "relayVideoThumbnail"
                                        anchors.fill: parent
                                        visible: attachmentPreview.modelData.available === true
                                                 && attachmentPreview.modelData.media_category === "video"

                                        Rectangle {
                                            anchors.centerIn: parent
                                            width: 42
                                            height: 42
                                            radius: 21
                                            color: "#cc102a5e"
                                            border.color: "white"
                                            border.width: 2

                                            Canvas {
                                                anchors.centerIn: parent
                                                width: 17
                                                height: 20

                                                onPaint: {
                                                    let context = getContext("2d")
                                                    context.clearRect(0, 0, width, height)
                                                    context.fillStyle = "white"
                                                    context.beginPath()
                                                    context.moveTo(2, 1)
                                                    context.lineTo(width - 1, height / 2)
                                                    context.lineTo(2, height - 1)
                                                    context.closePath()
                                                    context.fill()
                                                }
                                            }
                                        }

                                        Label {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.bottom: parent.bottom
                                            anchors.margins: 6
                                            text: attachmentPreview.modelData.label || "VIDEO"
                                            color: "white"
                                            font.pixelSize: 10
                                            font.bold: true
                                            horizontalAlignment: Text.AlignHCenter
                                            elide: Text.ElideMiddle
                                        }
                                    }

                                    Label {
                                        id: audioTile
                                        objectName: "relayAudioTile"
                                        anchors.fill: parent
                                        anchors.margins: 8
                                        visible: attachmentPreview.modelData.available === true
                                                 && attachmentPreview.modelData.media_category === "audio"
                                        text: "PLAY AUDIO  ·  "
                                              + (attachmentPreview.modelData.label || "AUDIO MESSAGE")
                                        color: "white"
                                        font.pixelSize: 12
                                        font.bold: true
                                        verticalAlignment: Text.AlignVCenter
                                        elide: Text.ElideMiddle
                                    }

                                    Label {
                                        anchors.fill: parent
                                        anchors.margins: 8
                                        visible: attachmentPreview.modelData.available !== true
                                        text: (attachmentPreview.modelData.label || "ATTACHMENT")
                                              + " UNAVAILABLE"
                                        color: "#58708c"
                                        font.pixelSize: 11
                                        font.bold: true
                                        verticalAlignment: Text.AlignVCenter
                                        horizontalAlignment: Text.AlignHCenter
                                        elide: Text.ElideMiddle
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        enabled: attachmentPreview.modelData.available === true
                                        onClicked: root.send(
                                            "relay_open_attachment",
                                            attachmentPreview.modelData.path
                                        )
                                    }
                                }
                            }
                        }
                    }

                    Row {
                        id: reactionBadges
                        anchors.right: parent.right
                        anchors.rightMargin: 7
                        anchors.top: parent.top
                        anchors.topMargin: 17
                        spacing: 3
                        visible: (messageCard.modelData.reactions || []).length > 0

                        Repeater {
                            model: messageCard.modelData.reactions || []

                            delegate: Rectangle {
                                required property var modelData
                                width: modelData.count > 1 ? 39 : 26
                                height: 24
                                radius: 12
                                color: "#d9f3ff"
                                border.width: 1
                                border.color: "#8fcde6"

                                Row {
                                    anchors.centerIn: parent
                                    spacing: 2

                                    Image {
                                        width: 16
                                        height: 16
                                        sourceSize.width: 32
                                        sourceSize.height: 32
                                        source: root.reactionIcon(modelData.kind)
                                        fillMode: Image.PreserveAspectFit
                                    }

                                    Label {
                                        visible: modelData.count > 1
                                        text: modelData.count
                                        color: "#102a5e"
                                        font.pixelSize: 10
                                        font.bold: true
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Label {
                Layout.fillWidth: true
                visible: (viewModel.error || "") !== ""
                text: viewModel.error || ""
                color: "#b3261e"
                font.bold: true
                wrapMode: Text.Wrap
            }
        }
    }

    Rectangle {
        id: mediaViewer
        objectName: "relayMediaViewer"
        anchors.fill: parent
        anchors.margins: 16
        radius: 14
        color: "#102a5e"
        visible: viewModel.selectedAttachment !== null
                 && viewModel.selectedAttachment !== undefined
        z: 3

        property var selected: viewModel.selectedAttachment || {}
        property string mediaCategory: selected.mediaCategory || ""

        Image {
            id: photoViewer
            objectName: "relayPhotoViewer"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: viewerControls.top
            anchors.margins: 10
            visible: mediaViewer.mediaCategory === "photo"
            source: mediaViewer.mediaCategory === "photo"
                ? (mediaViewer.selected.source || "")
                : ""
            fillMode: Image.PreserveAspectFit
            asynchronous: true
        }

        VideoOutput {
            id: videoOutput
            objectName: "relayVideoViewer"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: viewerControls.top
            anchors.margins: 10
            visible: mediaViewer.mediaCategory === "video"
            fillMode: VideoOutput.PreserveAspectFit
        }

        Column {
            anchors.centerIn: parent
            width: parent.width - 80
            spacing: 10
            visible: mediaViewer.mediaCategory === "audio"

            Label {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: "AUDIO MESSAGE"
                color: "#5bc9c2"
                font.pixelSize: 25
                font.bold: true
            }

            Label {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: mediaViewer.selected.label || "Audio"
                color: "white"
                font.pixelSize: 16
                elide: Text.ElideMiddle
            }
        }

        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: viewerControls.top
            anchors.bottomMargin: 8
            width: parent.width - 40
            visible: (mediaViewer.mediaCategory === "video"
                      || mediaViewer.mediaCategory === "audio")
                     && mediaPlayer.error !== MediaPlayer.NoError
            horizontalAlignment: Text.AlignHCenter
            text: mediaPlayer.errorString || "This attachment could not be played."
            color: "#ffb3bd"
            font.pixelSize: 13
            font.bold: true
            elide: Text.ElideRight
        }

        RowLayout {
            id: viewerControls
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 10
            height: 42
            spacing: 8

            Button {
                text: "BACK TO MESSAGES"
                onClicked: root.send("relay_close_attachment")
            }

            Label {
                Layout.fillWidth: true
                text: mediaViewer.selected.label || "ATTACHMENT"
                color: "white"
                font.pixelSize: 13
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideMiddle
            }

            Button {
                visible: mediaViewer.mediaCategory === "video"
                         || mediaViewer.mediaCategory === "audio"
                text: mediaPlayer.playbackState === MediaPlayer.PlayingState
                    ? "PAUSE"
                    : "PLAY"
                onClicked: {
                    if (mediaPlayer.playbackState === MediaPlayer.PlayingState)
                        mediaPlayer.pause()
                    else
                        mediaPlayer.play()
                }
            }

            Button {
                visible: mediaViewer.mediaCategory === "video"
                         || mediaViewer.mediaCategory === "audio"
                text: "RESTART"
                onClicked: {
                    mediaPlayer.position = 0
                    mediaPlayer.play()
                }
            }
        }
    }
}
