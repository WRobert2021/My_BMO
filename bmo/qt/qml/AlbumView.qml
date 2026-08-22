import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Basic as Basic

Item {
    id: albumView
    objectName: "albumRoot"

    required property var controller
    required property var viewModel

    function send(action, value) {
        controller.requestViewAction(
            action,
            value === undefined ? "" : String(value)
        )
    }

    component AlbumButton: Basic.Button {
        id: albumButtonControl

        property color fillColor: "#1578d3"
        property color pressedColor: Qt.darker(fillColor, 1.12)
        property color textColor: "white"
        property color outlineColor: "transparent"
        property int labelSize: 14

        scale: down ? 0.96 : 1.0
        opacity: enabled ? 1.0 : 0.42

        Behavior on scale {
            NumberAnimation { duration: 80 }
        }

        background: Rectangle {
            radius: 12
            color: albumButtonControl.down
                   ? albumButtonControl.pressedColor
                   : albumButtonControl.fillColor
            border.color: albumButtonControl.outlineColor
            border.width: albumButtonControl.outlineColor === "transparent" ? 0 : 2
        }

        contentItem: Text {
            text: albumButtonControl.text
            color: albumButtonControl.textColor
            font.pixelSize: albumButtonControl.labelSize
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#eafaff" }
            GradientStop { position: 0.64; color: "#f1f9ff" }
            GradientStop { position: 1.0; color: "#fff6dc" }
        }
    }

    Rectangle {
        x: -38
        y: 226
        width: 108
        height: 108
        radius: 54
        color: "#5bc9c2"
        opacity: 0.09
    }

    Rectangle {
        x: 744
        y: 296
        width: 94
        height: 94
        radius: 47
        color: "#f2c84b"
        opacity: 0.13
    }

    Column {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 12
        anchors.bottomMargin: 14
        spacing: 9

        Rectangle {
            id: albumSummary
            objectName: "albumSummaryCard"
            width: parent.width
            height: 52
            radius: 14
            color: "#fbfeff"
            border.color: "#9bd7e5"
            border.width: 2

            Rectangle {
                id: albumBadge
                anchors.left: parent.left
                anchors.leftMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                width: 38
                height: 38
                radius: 12
                color: "#d9f5f2"
                border.color: "#41aaa5"
                border.width: 2

                Rectangle {
                    x: 7
                    y: 9
                    width: 24
                    height: 19
                    radius: 3
                    color: "#ffffff"
                    border.color: "#365d72"
                    border.width: 2

                    Rectangle {
                        x: 4
                        y: 4
                        width: 6
                        height: 6
                        radius: 3
                        color: "#f2c84b"
                    }

                    Rectangle {
                        x: 10
                        y: 11
                        width: 10
                        height: 6
                        rotation: -24
                        color: "#5bc9c2"
                    }
                }
            }

            Label {
                anchors.left: albumBadge.right
                anchors.leftMargin: 10
                anchors.right: pageControls.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                text: {
                    let count = albumView.viewModel.photoCount || 0
                    if (count === 0)
                        return "Ready for your first photo!"
                    if (count === 1)
                        return "1 photo memory"
                    return count + " photo memories"
                }
                color: "#365d72"
                font.pixelSize: 18
                font.bold: true
                elide: Text.ElideRight
            }

            Row {
                id: pageControls
                anchors.right: parent.right
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6

                AlbumButton {
                    objectName: "albumPreviousButton"
                    width: 48
                    height: 40
                    text: "◀"
                    fillColor: "#e8f7fb"
                    pressedColor: "#cdebf3"
                    textColor: "#102a5e"
                    outlineColor: "#9bd7e5"
                    labelSize: 18
                    enabled: albumView.viewModel.detail !== true
                             && albumView.viewModel.hasPrevious === true
                    onClicked: albumView.send("album_previous")
                }

                Rectangle {
                    width: 72
                    height: 40
                    radius: 10
                    color: "#fff7dc"
                    border.color: "#efd064"
                    border.width: 2

                    Label {
                        anchors.centerIn: parent
                        text: albumView.viewModel.pageLabel || "--"
                        color: "#102a5e"
                        font.pixelSize: 14
                        font.bold: true
                    }
                }

                AlbumButton {
                    objectName: "albumNextButton"
                    width: 48
                    height: 40
                    text: "▶"
                    fillColor: "#e8f7fb"
                    pressedColor: "#cdebf3"
                    textColor: "#102a5e"
                    outlineColor: "#9bd7e5"
                    labelSize: 18
                    enabled: albumView.viewModel.detail !== true
                             && albumView.viewModel.hasNext === true
                    onClicked: albumView.send("album_next")
                }
            }
        }

        Rectangle {
            width: parent.width
            height: 34
            radius: 10
            visible: (albumView.viewModel.error || "") !== ""
            color: "#fff0f2"
            border.color: "#ed9aab"

            Label {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignHCenter
                text: albumView.viewModel.error || ""
                color: "#a92f47"
                font.pixelSize: 14
                font.bold: true
                elide: Text.ElideRight
            }
        }

        Item {
            id: albumContent
            objectName: "albumContent"
            width: parent.width
            height: parent.height - y

            GridView {
                id: photoGrid
                objectName: "albumPhotoGrid"
                anchors.fill: parent
                visible: albumView.viewModel.detail !== true
                         && (albumView.viewModel.photos || []).length > 0
                clip: true
                interactive: false
                model: albumView.viewModel.photos || []
                cellWidth: width / 3
                cellHeight: height / 2

                delegate: Item {
                    required property var modelData
                    required property int index
                    width: photoGrid.cellWidth
                    height: photoGrid.cellHeight

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 4
                        radius: 12
                        color: index % 3 === 0 ? "#f4fcfb"
                              : index % 3 === 1 ? "#fffaf0" : "#fff5f8"
                        border.color: index % 3 === 0 ? "#8edbd5"
                                      : index % 3 === 1 ? "#efd064" : "#efa4b7"
                        border.width: 2

                        Image {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.bottom: caption.top
                            anchors.margins: 5
                            anchors.bottomMargin: 3
                            source: modelData.source
                            fillMode: Image.PreserveAspectCrop
                        }

                        Label {
                            id: caption
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.leftMargin: 9
                            anchors.rightMargin: 9
                            height: 24
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: Text.AlignHCenter
                            text: modelData.label
                            color: "#365d72"
                            font.pixelSize: 12
                            font.bold: true
                            elide: Text.ElideMiddle
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: albumView.send("album_select", modelData.path)
                        }
                    }
                }
            }

            Rectangle {
                objectName: "albumEmptyCard"
                anchors.centerIn: parent
                width: 470
                height: 150
                radius: 20
                visible: albumView.viewModel.detail !== true
                         && (albumView.viewModel.photos || []).length === 0
                color: "#fbfeff"
                border.color: "#9bd7e5"
                border.width: 2

                Column {
                    anchors.centerIn: parent
                    width: parent.width - 40
                    spacing: 8

                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: "YOUR ALBUM IS READY"
                        color: "#102a5e"
                        font.pixelSize: 21
                        font.bold: true
                    }

                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        text: "New pictures will appear here for you to explore with BMO."
                        color: "#58708c"
                        font.pixelSize: 15
                    }
                }
            }

            Row {
                id: albumDetail
                objectName: "albumDetail"
                anchors.fill: parent
                visible: albumView.viewModel.detail === true
                spacing: 14

                Rectangle {
                    id: photoStage
                    objectName: "albumPhotoStage"
                    width: parent.width - actionPanel.width - parent.spacing
                    height: parent.height
                    radius: 14
                    color: "#102a5e"
                    border.color: "#5bc9c2"
                    border.width: 2

                    Image {
                        anchors.fill: parent
                        anchors.margins: 8
                        anchors.bottomMargin: 34
                        source: albumView.viewModel.selectedSource || ""
                        fillMode: Image.PreserveAspectFit
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 30
                        color: "#cc102a5e"
                        radius: 12

                        Label {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: Text.AlignHCenter
                            text: albumView.viewModel.selectedLabel || "PHOTO"
                            color: "white"
                            font.pixelSize: 13
                            font.bold: true
                            elide: Text.ElideMiddle
                        }
                    }
                }

                Rectangle {
                    id: actionPanel
                    objectName: "albumActionPanel"
                    width: 210
                    height: parent.height
                    radius: 14
                    color: "#fbfeff"
                    border.color: "#9bd7e5"
                    border.width: 2

                    Column {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 8

                        Label {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            text: "PHOTO ADVENTURE"
                            color: "#102a5e"
                            font.pixelSize: 15
                            font.bold: true
                        }

                        Label {
                            width: parent.width
                            height: 42
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            wrapMode: Text.Wrap
                            text: albumView.viewModel.busy
                                  ? "BMO is studying every detail!"
                                  : "Ask BMO to tell you about this picture."
                            color: "#58708c"
                            font.pixelSize: 13
                        }

                        AlbumButton {
                            width: parent.width
                            height: 58
                            text: albumView.viewModel.busy
                                  ? "BMO IS LOOKING..."
                                  : "WHAT DO YOU SEE?"
                            fillColor: "#3b9b6f"
                            pressedColor: "#2e805a"
                            labelSize: 13
                            enabled: albumView.viewModel.busy !== true
                            onClicked: albumView.send("album_vision")
                        }

                        AlbumButton {
                            width: parent.width
                            height: 52
                            text: "BACK TO PHOTOS"
                            fillColor: "#1578d3"
                            pressedColor: "#0f64b4"
                            labelSize: 13
                            enabled: albumView.viewModel.busy !== true
                            onClicked: albumView.send("album_back")
                        }

                        AlbumButton {
                            width: parent.width
                            height: 48
                            text: "MOVE TO WASTEBASKET"
                            fillColor: "#fff0f2"
                            pressedColor: "#f7d7de"
                            textColor: "#a92f47"
                            outlineColor: "#ed9aab"
                            labelSize: 11
                            enabled: albumView.viewModel.busy !== true
                            onClicked: albumView.send("album_delete")
                        }
                    }
                }
            }
        }
    }
}
