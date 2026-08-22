import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Basic as Basic

Item {
    id: timerView

    required property var controller
    property var viewModel: controller.viewData

    function send(action, value) {
        controller.requestViewAction(
            action,
            value === undefined ? "" : String(value)
        )
    }

    component TimerButton: Basic.Button {
        id: timerButtonControl

        property color fillColor: "#1578d3"
        property color pressedColor: Qt.darker(fillColor, 1.12)
        property color textColor: "white"
        property color outlineColor: "transparent"
        property int cornerRadius: 12
        property int labelSize: 14

        scale: down ? 0.96 : 1.0
        opacity: enabled ? 1.0 : 0.45

        Behavior on scale {
            NumberAnimation { duration: 80 }
        }

        background: Rectangle {
            radius: timerButtonControl.cornerRadius
            color: timerButtonControl.down
                   ? timerButtonControl.pressedColor
                   : timerButtonControl.fillColor
            border.color: timerButtonControl.outlineColor
            border.width: timerButtonControl.outlineColor === "transparent" ? 0 : 2
        }

        contentItem: Text {
            text: timerButtonControl.text
            color: timerButtonControl.textColor
            font.pixelSize: timerButtonControl.labelSize
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
            GradientStop { position: 1.0; color: "#fff8df" }
        }
    }

    Rectangle {
        x: -32
        y: 245
        width: 112
        height: 112
        radius: 56
        color: "#5bc9c2"
        opacity: 0.09
    }

    Rectangle {
        x: 742
        y: 300
        width: 96
        height: 96
        radius: 48
        color: "#f2c84b"
        opacity: 0.13
    }

    Column {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 12
        anchors.bottomMargin: 14
        spacing: 10

        Rectangle {
            id: timerSummary
            objectName: "timerSummaryCard"
            width: parent.width
            height: 52
            radius: 14
            color: "#f9fdff"
            border.color: "#9bd7e5"
            border.width: 2

            Rectangle {
                id: timerClockBadge
                anchors.left: parent.left
                anchors.leftMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                width: 36
                height: 36
                radius: 18
                color: "#d9f5f2"
                border.color: "#41aaa5"
                border.width: 2

                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 8
                    width: 2
                    height: 10
                    radius: 1
                    color: "#102a5e"
                }

                Rectangle {
                    x: 17
                    y: 17
                    width: 9
                    height: 2
                    radius: 1
                    color: "#102a5e"
                    rotation: 25
                    transformOrigin: Item.Left
                }
            }

            Label {
                anchors.left: timerClockBadge.right
                anchors.leftMargin: 10
                anchors.right: newTimerButton.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                text: {
                    let count = (timerView.viewModel.items || []).length
                    if (count === 0)
                        return "Ready for a countdown!"
                    if (count === 1)
                        return "1 timer ticking"
                    return count + " timers ticking"
                }
                color: "#365d72"
                font.pixelSize: 18
                font.bold: true
                elide: Text.ElideRight
            }

            TimerButton {
                id: newTimerButton
                anchors.right: parent.right
                anchors.rightMargin: 5
                anchors.verticalCenter: parent.verticalCenter
                width: 150
                height: 42
                fillColor: timerView.viewModel.adding ? "#f08aa6" : "#1578d3"
                pressedColor: timerView.viewModel.adding ? "#d76f8d" : "#0f64b4"
                text: timerView.viewModel.adding ? "CLOSE EDITOR" : "+ NEW TIMER"
                labelSize: 13
                onClicked: timerView.send(
                    timerView.viewModel.adding ? "timer_cancel_add" : "timer_add"
                )
            }
        }

        Rectangle {
            id: timerEditor
            objectName: "timerAddEditor"
            width: parent.width
            height: 104
            visible: timerView.viewModel.adding === true
            radius: 16
            color: "#fffaf0"
            border.color: "#e6bd42"
            border.width: 2

            Row {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 8

                Repeater {
                    model: ["hours", "minutes", "seconds"]

                    delegate: Rectangle {
                        required property string modelData
                        width: 196
                        height: 88
                        radius: 12
                        color: "#ffffff"
                        border.color: modelData === "hours" ? "#8edbd5"
                                      : modelData === "minutes" ? "#f1d36d"
                                      : "#f2a8ba"
                        border.width: 2

                        Label {
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: 6
                            text: modelData.toUpperCase()
                            color: "#58708c"
                            font.pixelSize: 12
                            font.bold: true
                            font.letterSpacing: 0.6
                        }

                        Row {
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: 32
                            spacing: 5

                            TimerButton {
                                width: 44
                                height: 46
                                text: "−"
                                fillColor: "#eaf7fb"
                                pressedColor: "#cdebf3"
                                textColor: "#102a5e"
                                outlineColor: "#9bd7e5"
                                labelSize: 23
                                onClicked: timerView.send(
                                    "timer_adjust",
                                    JSON.stringify({
                                        field: modelData,
                                        amount: -1
                                    })
                                )
                            }

                            Label {
                                width: 72
                                height: 46
                                verticalAlignment: Text.AlignVCenter
                                horizontalAlignment: Text.AlignHCenter
                                text: timerView.viewModel[modelData] || 0
                                font.pixelSize: 24
                                font.bold: true
                                color: "#102a5e"
                            }

                            TimerButton {
                                width: 44
                                height: 46
                                text: "+"
                                fillColor: "#eaf7fb"
                                pressedColor: "#cdebf3"
                                textColor: "#102a5e"
                                outlineColor: "#9bd7e5"
                                labelSize: 22
                                onClicked: timerView.send(
                                    "timer_adjust",
                                    JSON.stringify({
                                        field: modelData,
                                        amount: 1
                                    })
                                )
                            }
                        }
                    }
                }

                TimerButton {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 136
                    height: 76
                    text: "START TIMER"
                    fillColor: "#3b9b6f"
                    pressedColor: "#2e805a"
                    labelSize: 14
                    onClicked: timerView.send("timer_create")
                }
            }
        }

        Rectangle {
            width: parent.width
            height: 34
            radius: 10
            visible: (timerView.viewModel.error || "") !== ""
            color: "#fff0f2"
            border.color: "#ed9aab"

            Label {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignHCenter
                text: timerView.viewModel.error || ""
                color: "#a92f47"
                font.pixelSize: 14
                font.bold: true
                elide: Text.ElideRight
            }
        }

        Item {
            width: parent.width
            height: parent.height - y

            ListView {
                id: timerList
                objectName: "timerList"
                anchors.fill: parent
                spacing: 8
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                interactive: contentHeight > height
                model: timerView.viewModel.items || []

                ScrollIndicator.vertical: ScrollIndicator {
                    active: timerList.moving || timerList.contentHeight > timerList.height
                }

                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    width: ListView.view.width
                    height: 68
                    radius: 13
                    color: index % 3 === 0 ? "#f4fcfb"
                          : index % 3 === 1 ? "#fffaf0" : "#fff5f8"
                    border.color: index % 3 === 0 ? "#8edbd5"
                                  : index % 3 === 1 ? "#efd064" : "#efa4b7"
                    border.width: 2

                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 7
                        radius: 3
                        color: index % 3 === 0 ? "#41aaa5"
                              : index % 3 === 1 ? "#d7a91f" : "#dd718e"
                    }

                    Rectangle {
                        id: timerNumberBadge
                        anchors.left: parent.left
                        anchors.leftMargin: 17
                        anchors.verticalCenter: parent.verticalCenter
                        width: 38
                        height: 38
                        radius: 19
                        color: index % 3 === 0 ? "#d9f5f2"
                              : index % 3 === 1 ? "#fff0b8" : "#ffe0e8"

                        Label {
                            anchors.centerIn: parent
                            text: modelData.id
                            color: "#102a5e"
                            font.pixelSize: 15
                            font.bold: true
                        }
                    }

                    Label {
                        id: timerLabel
                        objectName: "timerRowLabel"
                        anchors.left: timerNumberBadge.right
                        anchors.leftMargin: 12
                        anchors.right: timerRemaining.left
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.label
                        color: "#102a5e"
                        font.pixelSize: 18
                        font.bold: true
                        elide: Text.ElideRight
                    }

                    Label {
                        id: timerRemaining
                        objectName: "timerRowRemaining"
                        anchors.right: removeTimerButton.left
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        width: 160
                        horizontalAlignment: Text.AlignRight
                        text: modelData.remaining
                        color: "#1578d3"
                        font.pixelSize: 24
                        font.bold: true
                        font.letterSpacing: 0.5
                    }

                    TimerButton {
                        id: removeTimerButton
                        objectName: "timerRemoveButton"
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        width: 104
                        height: 46
                        text: "REMOVE"
                        fillColor: "#d95870"
                        pressedColor: "#bd4058"
                        labelSize: 12
                        onClicked: timerView.send("timer_cancel", modelData.id)
                    }
                }
            }

            Rectangle {
                anchors.centerIn: parent
                width: Math.min(480, parent.width - 36)
                height: 144
                radius: 20
                visible: timerList.count === 0
                color: "#f9fdff"
                border.color: "#9bd7e5"
                border.width: 2

                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 15
                    width: 44
                    height: 44
                    radius: 22
                    color: "#d9f5f2"
                    border.color: "#41aaa5"
                    border.width: 2

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        y: 10
                        width: 3
                        height: 12
                        radius: 1.5
                        color: "#102a5e"
                    }

                    Rectangle {
                        x: 21
                        y: 21
                        width: 11
                        height: 3
                        radius: 1.5
                        color: "#102a5e"
                        rotation: 25
                        transformOrigin: Item.Left
                    }
                }

                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 65
                    text: "No timers are ticking yet"
                    color: "#102a5e"
                    font.pixelSize: 20
                    font.bold: true
                }

                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 98
                    text: "Tap + NEW TIMER to start one."
                    color: "#58708c"
                    font.pixelSize: 14
                    font.bold: true
                }
            }
        }
    }
}
