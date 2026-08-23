import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    objectName: "galaxyRvrRoot"
    required property var controller
    required property var viewModel

    property int previewToken: 0
    property bool showFirstPreview: false
    property bool previewActive: viewModel.previewEnabled === true
                                 && viewModel.rover_connected === true

    function send(action, value) {
        controller.requestViewAction(action, value === undefined ? "" : String(value))
    }

    function requestPreview() {
        if (!previewActive || viewModel.taking_photo === true)
            return
        let target = showFirstPreview ? previewSecond : previewFirst
        if (target.status === Image.Loading)
            return
        previewToken += 1
        target.source = viewModel.captureUrl + "?t=" + previewToken
    }

    function distanceText() {
        let value = viewModel.ultrasonic_cm
        return value === null || value === undefined ? "--" : Number(value).toFixed(1) + " cm"
    }

    function irText(value) {
        if (value === null || value === undefined)
            return "--"
        return value === true ? "BLOCKED" : "CLEAR"
    }

    function batteryText() {
        let value = viewModel.battery_voltage
        return value === null || value === undefined ? "--" : Number(value).toFixed(2) + " V"
    }

    function selectedColor(hexColor) {
        if (viewModel.rgb_selected !== true || !hexColor || hexColor.length !== 7)
            return false
        return viewModel.rgb_red === parseInt(hexColor.slice(1, 3), 16)
            && viewModel.rgb_green === parseInt(hexColor.slice(3, 5), 16)
            && viewModel.rgb_blue === parseInt(hexColor.slice(5, 7), 16)
    }

    onPreviewActiveChanged: {
        if (!previewActive) {
            previewFirst.source = ""
            previewSecond.source = ""
            showFirstPreview = false
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "#e9f7fb"
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#e8fbff" }
            GradientStop { position: 0.62; color: "#eef8ff" }
            GradientStop { position: 1.0; color: "#fff4d8" }
        }
    }

    Rectangle {
        x: -38
        y: 250
        width: 116
        height: 116
        radius: 58
        color: "#5bc9c2"
        opacity: 0.10
    }

    Rectangle {
        x: 735
        y: 16
        width: 92
        height: 92
        radius: 46
        color: "#f2c84b"
        opacity: 0.13
    }

    Timer {
        interval: Math.max(100, viewModel.previewIntervalMs || 250)
        running: page.previewActive && viewModel.taking_photo !== true
        repeat: true
        triggeredOnStart: true
        onTriggered: page.requestPreview()
    }

    Row {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 12

        Rectangle {
            id: cameraCard
            objectName: "galaxyRvrCameraCard"
            width: 500
            height: parent.height
            radius: 16
            color: "#102a5e"
            border.color: "#77cbd3"
            border.width: 2

            Label {
                x: 14
                y: 8
                text: "EXPLORER CAMERA"
                color: "white"
                font.pixelSize: 16
                font.bold: true
                font.letterSpacing: 0.6
            }

            Rectangle {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 9
                width: 116
                height: 23
                radius: 12
                color: viewModel.rover_connected === true ? "#43b581" : "#667a96"

                Label {
                    anchors.centerIn: parent
                    text: viewModel.rover_connected === true ? "●  ROVER LIVE" : "○  CONNECTING"
                    color: "white"
                    font.pixelSize: 11
                    font.bold: true
                }
            }

            Rectangle {
                id: previewArea
                x: 8
                y: 39
                width: parent.width - 16
                height: parent.height - 118
                radius: 10
                color: "#071a38"
                clip: true

                Image {
                    id: previewFirst
                    anchors.fill: parent
                    anchors.margins: 5
                    visible: page.previewActive
                             && page.showFirstPreview
                             && status === Image.Ready
                    cache: false
                    asynchronous: true
                    fillMode: Image.PreserveAspectFit
                    onStatusChanged: {
                        if (status === Image.Ready)
                            page.showFirstPreview = true
                    }
                }

                Image {
                    id: previewSecond
                    anchors.fill: parent
                    anchors.margins: 5
                    visible: page.previewActive
                             && !page.showFirstPreview
                             && status === Image.Ready
                    cache: false
                    asynchronous: true
                    fillMode: Image.PreserveAspectFit
                    onStatusChanged: {
                        if (status === Image.Ready)
                            page.showFirstPreview = false
                    }
                }

                Column {
                    anchors.centerIn: parent
                    width: parent.width - 40
                    spacing: 7
                    visible: !page.previewActive
                             || (previewFirst.status !== Image.Ready
                                 && previewSecond.status !== Image.Ready)

                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: page.previewActive
                              ? "WAKING UP THE CAMERA…"
                              : (viewModel.rover_connected === true
                                 ? "CAMERA PREVIEW IS OFF"
                                 : "SEARCHING FOR GALAXYRVR…")
                        color: "white"
                        font.pixelSize: 20
                        font.bold: true
                    }

                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: "Rover address  •  " + (viewModel.host || "")
                        color: "#9de0e2"
                        font.pixelSize: 13
                    }
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 7
                    height: 43
                    radius: 9
                    color: "#dc102a5e"

                    Column {
                        anchors.centerIn: parent
                        spacing: 1

                        Label {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "MOTORS  " + (viewModel.left_power || 0)
                                  + " / " + (viewModel.right_power || 0)
                                  + "     CAMERA  " + (viewModel.servo_angle || 0) + "°"
                            color: "white"
                            font.pixelSize: 13
                            font.bold: true
                        }

                        Label {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: viewModel.axis_summary || "Controller inputs waiting…"
                            color: "#bde7ff"
                            font.pixelSize: 10
                        }
                    }
                }
            }

            Row {
                objectName: "galaxyRvrSensorRow"
                x: 8
                y: parent.height - 72
                width: parent.width - 16
                height: 64
                spacing: 6

                Repeater {
                    model: [
                        { title: "SONIC", value: page.distanceText(), kind: "sonic" },
                        { title: "LEFT IR", value: page.irText(viewModel.ir_left_detected), kind: "left" },
                        { title: "RIGHT IR", value: page.irText(viewModel.ir_right_detected), kind: "right" },
                        { title: "BATTERY", value: page.batteryText(), kind: "battery" }
                    ]

                    delegate: Rectangle {
                        required property var modelData
                        width: 116.5
                        height: 64
                        radius: 10
                        color: {
                            if (modelData.kind === "sonic"
                                    && viewModel.ultrasonic_cm !== null
                                    && viewModel.ultrasonic_cm !== undefined
                                    && viewModel.ultrasonic_cm < 20)
                                return "#8f3f55"
                            if ((modelData.kind === "left" && viewModel.ir_left_detected === true)
                                    || (modelData.kind === "right" && viewModel.ir_right_detected === true))
                                return "#8f3f55"
                            if (modelData.kind === "battery"
                                    && viewModel.battery_voltage !== null
                                    && viewModel.battery_voltage !== undefined
                                    && viewModel.battery_voltage < 6.6)
                                return "#8f3f55"
                            return "#164b78"
                        }
                        border.color: modelData.value === "--" ? "#55728f" : "#5bc9c2"
                        border.width: 1

                        Column {
                            anchors.centerIn: parent
                            spacing: 2

                            Label {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.title
                                color: "#9de0e2"
                                font.pixelSize: 10
                                font.bold: true
                            }

                            Label {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.value
                                color: "white"
                                font.pixelSize: 14
                                font.bold: true
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            id: controlCard
            objectName: "galaxyRvrControlCard"
            width: 268
            height: parent.height
            radius: 16
            color: "#fbfeff"
            border.color: "#9bd7e5"
            border.width: 2

            Column {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 7

                Rectangle {
                    width: parent.width
                    height: 48
                    radius: 11
                    color: viewModel.error ? "#fff0f1" : "#e8f8f5"
                    border.color: viewModel.error ? "#e78991" : "#8ad4c9"

                    Label {
                        anchors.fill: parent
                        anchors.margins: 7
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        text: viewModel.error || viewModel.state || "Starting remote…"
                        color: viewModel.error ? "#a82f3a" : "#164b78"
                        font.pixelSize: 13
                        font.bold: true
                    }
                }

                Label {
                    width: parent.width
                    text: "✨  LIGHT LAB"
                    color: "#102a5e"
                    font.pixelSize: 17
                    font.bold: true
                    font.letterSpacing: 0.5
                }

                GridLayout {
                    objectName: "galaxyRvrLightGrid"
                    width: parent.width
                    height: 85
                    columns: 4
                    rowSpacing: 5
                    columnSpacing: 5

                    Repeater {
                        model: viewModel.lightColors || []

                        delegate: Rectangle {
                            required property var modelData
                            Layout.preferredWidth: 55
                            Layout.preferredHeight: 40
                            radius: 9
                            color: modelData.hex
                            border.color: page.selectedColor(modelData.hex) ? "#102a5e" : "#9ab3c4"
                            border.width: page.selectedColor(modelData.hex) ? 4 : 1
                            opacity: viewModel.rover_connected === true ? 1.0 : 0.48

                            Label {
                                anchors.centerIn: parent
                                text: modelData.name
                                color: modelData.text
                                font.pixelSize: 9
                                font.bold: true
                            }

                            MouseArea {
                                anchors.fill: parent
                                enabled: viewModel.rover_connected === true
                                onClicked: page.send("galaxy_rvr_rgb", modelData.hex)
                            }
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 84
                    radius: 11
                    color: "#eef8ff"
                    border.color: "#c2dce9"

                    GridLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        columns: 2
                        rowSpacing: 4
                        columnSpacing: 8

                        Repeater {
                            model: viewModel.controls || []

                            delegate: Label {
                                required property string modelData
                                Layout.preferredWidth: 108
                                Layout.preferredHeight: 28
                                verticalAlignment: Text.AlignVCenter
                                wrapMode: Text.Wrap
                                text: modelData
                                color: "#365d72"
                                font.pixelSize: 11
                                font.bold: true
                            }
                        }
                    }
                }

                Button {
                    width: parent.width
                    height: 48
                    text: viewModel.taking_photo ? "SAVING PHOTO…" : "📸  SNAP PHOTO  (A)"
                    enabled: viewModel.taking_photo !== true
                             && viewModel.rover_connected === true
                    font.pixelSize: 14
                    font.bold: true
                    onClicked: page.send("galaxy_rvr_snapshot")
                }

                Label {
                    width: parent.width
                    height: 20
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideMiddle
                    text: (viewModel.last_photo || "") !== ""
                          ? "✓ Saved  " + viewModel.last_photo
                          : "Photos save to your rover album"
                    color: (viewModel.last_photo || "") !== "" ? "#278060" : "#6b8397"
                    font.pixelSize: 10
                    font.bold: (viewModel.last_photo || "") !== ""
                }
            }
        }
    }
}
