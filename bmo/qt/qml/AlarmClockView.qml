import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Basic as Basic

Item {
    id: root
    required property var controller
    property var viewModel: controller.viewData

    function send(action, value) {
        controller.requestViewAction(
            action,
            value === undefined ? "" : String(value)
        )
    }

    component ClockButton: Basic.Button {
        id: control
        property color fillColor: "#1578d3"
        property color textColor: "white"
        property color outlineColor: "transparent"
        property int labelSize: 14
        scale: down ? 0.96 : 1.0
        opacity: enabled ? 1.0 : 0.42
        Behavior on scale { NumberAnimation { duration: 80 } }
        background: Rectangle {
            radius: 12
            color: control.down ? Qt.darker(control.fillColor, 1.12) : control.fillColor
            border.color: control.outlineColor
            border.width: control.outlineColor === "transparent" ? 0 : 2
        }
        contentItem: Text {
            text: control.text
            color: control.textColor
            font.pixelSize: control.labelSize
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#e9faff" }
            GradientStop { position: 0.70; color: "#edf7ff" }
            GradientStop { position: 1.0; color: "#fff4d8" }
        }
    }

    Rectangle {
        x: -42; y: 262; width: 126; height: 126; radius: 63
        color: "#5bc9c2"; opacity: 0.10
    }
    Rectangle {
        x: 726; y: 280; width: 112; height: 112; radius: 56
        color: "#f2c84b"; opacity: 0.15
    }

    Row {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        Rectangle {
            objectName: "alarmDigitalClockCard"
            width: 274
            height: parent.height
            radius: 20
            color: "#102a5e"
            border.color: "#5bc9c2"
            border.width: 3

            Rectangle {
                x: 16; y: 18; width: 46; height: 10; radius: 5
                color: "#f08aa6"
            }
            Rectangle {
                x: 68; y: 18; width: 22; height: 10; radius: 5
                color: "#f2c84b"
            }

            Column {
                anchors.fill: parent
                anchors.margins: 16
                anchors.topMargin: 48
                spacing: 13

                Label {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: root.viewModel.clock || "--:--"
                    color: "#f7fdff"
                    font.pixelSize: 46
                    font.bold: true
                    font.letterSpacing: 1.2
                }
                Label {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: ":" + (root.viewModel.seconds || "00")
                    color: "#9ee8e1"
                    font.pixelSize: 17
                    font.bold: true
                }
                Label {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: root.viewModel.date || ""
                    color: "#c9e9f7"
                    font.pixelSize: 16
                    font.bold: true
                    wrapMode: Text.Wrap
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: "#5bc9c2"
                    opacity: 0.55
                }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8
                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "12 HOUR"
                        color: root.viewModel.use24Hour ? "#829bb7" : "white"
                        font.pixelSize: 12
                        font.bold: true
                    }
                    Switch {
                        id: clockFormatSwitch
                        objectName: "alarmClockFormatSwitch"
                        checked: root.viewModel.use24Hour === true
                        enabled: root.viewModel.readOnly !== true
                        onToggled: root.send("alarm_24_hour", checked)
                    }
                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "24 HOUR"
                        color: root.viewModel.use24Hour ? "white" : "#829bb7"
                        font.pixelSize: 12
                        font.bold: true
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 52
                    radius: 14
                    color: root.viewModel.ringing ? "#f08aa6" : "#173e6d"
                    border.color: root.viewModel.ringing ? "#ffdce5" : "#2c668e"
                    border.width: 2
                    Label {
                        anchors.centerIn: parent
                        width: parent.width - 20
                        horizontalAlignment: Text.AlignHCenter
                        text: root.viewModel.ringing
                              ? "ALARM RINGING!"
                              : ((root.viewModel.items || []).length + " SAVED ALARM" + ((root.viewModel.items || []).length === 1 ? "" : "S"))
                        color: "white"
                        font.pixelSize: 15
                        font.bold: true
                    }
                }
            }
        }

        Column {
            width: parent.width - 286
            height: parent.height
            spacing: 8

            Row {
                width: parent.width
                height: 48
                spacing: 8
                Label {
                    width: parent.width - 162
                    height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    text: "MY ALARMS"
                    color: "#102a5e"
                    font.pixelSize: 21
                    font.bold: true
                    font.letterSpacing: 0.6
                }
                ClockButton {
                    width: 154
                    height: 46
                    text: "+ NEW ALARM"
                    fillColor: "#3b9b6f"
                    enabled: root.viewModel.readOnly !== true
                    onClicked: root.send("alarm_add")
                }
            }

            Rectangle {
                width: parent.width
                height: 36
                radius: 10
                visible: (root.viewModel.error || "") !== ""
                color: "#fff0f2"
                border.color: "#ed9aab"
                Label {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: root.viewModel.error || ""
                    color: "#a92f47"
                    font.pixelSize: 13
                    font.bold: true
                    elide: Text.ElideRight
                }
            }

            ListView {
                id: alarmList
                objectName: "alarmClockList"
                width: parent.width
                height: parent.height - y
                model: root.viewModel.items || []
                spacing: 8
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                interactive: contentHeight > height
                ScrollIndicator.vertical: ScrollIndicator {
                    active: alarmList.moving || alarmList.contentHeight > alarmList.height
                }

                Label {
                    anchors.centerIn: parent
                    visible: alarmList.count === 0
                    width: parent.width - 40
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    text: "No alarms yet. Tap + NEW ALARM to make one!"
                    color: "#58708c"
                    font.pixelSize: 18
                    font.bold: true
                }

                delegate: Rectangle {
                    required property var modelData
                    width: alarmList.width - 4
                    height: modelData.ringing ? 108 : 86
                    radius: 16
                    color: modelData.ringing ? "#fff0f4" : "#fbfdff"
                    border.color: modelData.ringing ? "#f08aa6" : (modelData.enabled ? "#8edbd5" : "#c7d5df")
                    border.width: modelData.ringing ? 3 : 2
                    opacity: modelData.enabled || modelData.ringing || modelData.snoozed ? 1.0 : 0.68

                    Rectangle {
                        x: 0; y: 14; width: 7; height: parent.height - 28; radius: 3.5
                        color: modelData.ringing ? "#f08aa6" : (modelData.enabled ? "#5bc9c2" : "#aebdca")
                    }

                    Column {
                        x: 18; y: 9; width: 198; spacing: 1
                        Label {
                            text: modelData.time
                            color: "#102a5e"
                            font.pixelSize: 25
                            font.bold: true
                        }
                        Label {
                            width: parent.width
                            text: modelData.label
                            color: "#365d72"
                            font.pixelSize: 14
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        Label {
                            width: parent.width
                            text: modelData.snoozed ? "Snoozed" : modelData.repeat
                            color: modelData.snoozed ? "#b75a22" : "#71879b"
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                    }

                    Row {
                        anchors.right: parent.right
                        anchors.rightMargin: 8
                        y: 19
                        spacing: 6
                        visible: !modelData.ringing
                        ClockButton {
                            width: 66; height: 46
                            text: modelData.enabled ? "ON" : "OFF"
                            fillColor: modelData.enabled ? "#3b9b6f" : "#9aaab7"
                            onClicked: root.send("alarm_toggle", JSON.stringify({id: modelData.id, enabled: !modelData.enabled}))
                        }
                        ClockButton {
                            width: 66; height: 46
                            text: "EDIT"
                            fillColor: "#1578d3"
                            onClicked: root.send("alarm_edit", modelData.id)
                        }
                        ClockButton {
                            width: 72; height: 46
                            text: "DELETE"
                            fillColor: "#c83a4a"
                            labelSize: 11
                            onClicked: root.send("alarm_delete", modelData.id)
                        }
                    }

                    Row {
                        anchors.right: parent.right
                        anchors.rightMargin: 10
                        y: 28
                        spacing: 8
                        visible: modelData.ringing
                        ClockButton {
                            width: 106; height: 52
                            text: "SNOOZE " + (root.viewModel.snoozeMinutes || 9) + "m"
                            fillColor: "#e6a72c"
                            textColor: "#102a5e"
                            onClicked: root.send("alarm_snooze", modelData.id)
                        }
                        ClockButton {
                            width: 104; height: 52
                            text: "DISMISS"
                            fillColor: "#c83a4a"
                            onClicked: root.send("alarm_dismiss", modelData.id)
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        id: alarmEditor
        objectName: "alarmClockEditor"
        anchors.fill: parent
        anchors.margins: 12
        visible: root.viewModel.editing === true
        z: 20
        radius: 20
        color: "#f9fdff"
        border.color: "#5bc9c2"
        border.width: 3

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 54
            radius: 18
            color: "#164b78"
            Label {
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                text: (root.viewModel.editingId || 0) > 0 ? "EDIT ALARM" : "NEW ALARM"
                color: "white"
                font.pixelSize: 21
                font.bold: true
            }
        }

        Row {
            x: 24; y: 72; spacing: 16
            Rectangle {
                width: 310; height: 222; radius: 18
                color: "#102a5e"
                Column {
                    anchors.centerIn: parent
                    spacing: 14
                    Label {
                        width: 270
                        horizontalAlignment: Text.AlignHCenter
                        text: root.viewModel.draftTime || "--:--"
                        color: "white"
                        font.pixelSize: 42
                        font.bold: true
                    }
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 8
                        ClockButton { width: 60; height: 52; text: "H −"; fillColor: "#d9f5f2"; textColor: "#102a5e"; onClicked: root.send("alarm_adjust", JSON.stringify({field: "hour", amount: -1})) }
                        ClockButton { width: 60; height: 52; text: "H +"; fillColor: "#d9f5f2"; textColor: "#102a5e"; onClicked: root.send("alarm_adjust", JSON.stringify({field: "hour", amount: 1})) }
                        ClockButton { width: 60; height: 52; text: "M −"; fillColor: "#fff0bd"; textColor: "#102a5e"; onClicked: root.send("alarm_adjust", JSON.stringify({field: "minute", amount: -5})) }
                        ClockButton { width: 60; height: 52; text: "M +"; fillColor: "#fff0bd"; textColor: "#102a5e"; onClicked: root.send("alarm_adjust", JSON.stringify({field: "minute", amount: 5})) }
                    }
                    Label {
                        width: 270
                        horizontalAlignment: Text.AlignHCenter
                        text: "H = hour   •   M = minute"
                        color: "#a9dbea"
                        font.pixelSize: 12
                    }
                }
            }

            Column {
                width: 408
                spacing: 12
                Label { text: "NAME"; color: "#58708c"; font.pixelSize: 12; font.bold: true }
                TextField {
                    id: alarmNameField
                    width: parent.width; height: 48
                    text: root.viewModel.draftLabel || "Alarm"
                    maximumLength: 60
                    selectByMouse: true
                    onTextEdited: root.send("alarm_label", text)
                }
                Label { text: "REPEAT ON (leave blank for one time)"; color: "#58708c"; font.pixelSize: 12; font.bold: true }
                Row {
                    spacing: 5
                    Repeater {
                        model: ["M", "T", "W", "T", "F", "S", "S"]
                        delegate: ClockButton {
                            required property string modelData
                            required property int index
                            width: 52; height: 48
                            text: modelData
                            property bool selected: (root.viewModel.draftWeekdays || []).indexOf(index) !== -1
                            fillColor: selected ? (index < 5 ? "#5bc9c2" : "#f2c84b") : "#e5eef3"
                            textColor: "#102a5e"
                            outlineColor: selected ? "#187a85" : "#b8cad5"
                            onClicked: root.send("alarm_weekday", index)
                        }
                    }
                }
                Label {
                    width: parent.width
                    text: (root.viewModel.draftWeekdays || []).length === 0
                          ? "This alarm will ring once at the next matching time."
                          : "This alarm will repeat on the selected days."
                    color: "#365d72"
                    font.pixelSize: 13
                    wrapMode: Text.Wrap
                }
            }
        }

        Row {
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.margins: 18
            spacing: 10
            ClockButton {
                width: 130; height: 50; text: "CANCEL"
                fillColor: "#e5eef3"; textColor: "#102a5e"; outlineColor: "#b8cad5"
                onClicked: root.send("alarm_editor_cancel")
            }
            ClockButton {
                width: 174; height: 50; text: "SAVE ALARM"
                fillColor: "#3b9b6f"
                onClicked: root.send("alarm_save")
            }
        }
    }
}
