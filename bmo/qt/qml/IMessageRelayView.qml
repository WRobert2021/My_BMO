import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    required property var controller
    required property var viewModel

    function send(action, value) {
        controller.requestViewAction(action, value === undefined ? "" : String(value))
    }

    Rectangle {
        anchors.fill: parent
        color: "#e8f8fb"
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 14

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 82
                radius: 14
                color: "white"
                border.width: 2
                border.color: viewModel.healthy === true ? "#2f9f83" : "#d45555"

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 14

                    Rectangle {
                        width: 18
                        height: 18
                        radius: 9
                        color: viewModel.healthy === true ? "#45bd92" : "#db6565"
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Label {
                            text: viewModel.healthy === true ? "RECEIVER AVAILABLE" : "RECEIVER UNAVAILABLE"
                            color: "#102a5e"
                            font.pixelSize: 18
                            font.bold: true
                        }
                        Label {
                            Layout.fillWidth: true
                            text: viewModel.serviceMessage || ""
                            color: "#58708c"
                            font.pixelSize: 14
                            wrapMode: Text.Wrap
                        }
                    }
                    Button {
                        text: "REFRESH"
                        onClicked: send("relay_refresh")
                    }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 4
                columnSpacing: 8
                rowSpacing: 8

                Repeater {
                    model: [
                        { label: "RECEIVED", value: viewModel.receivedEvents || 0 },
                        { label: "PENDING", value: viewModel.pendingEvents || 0 },
                        { label: "ATTACHMENTS", value: viewModel.completeAttachments || 0 },
                        { label: "PARTIAL", value: viewModel.partialAttachments || 0 }
                    ]

                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: 74
                        radius: 12
                        color: "#102a5e"

                        Column {
                            anchors.centerIn: parent
                            spacing: 2
                            Label {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.value
                                color: "white"
                                font.pixelSize: 25
                                font.bold: true
                            }
                            Label {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: modelData.label
                                color: "#bde7ff"
                                font.pixelSize: 11
                                font.bold: true
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 14
                color: "white"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 9

                    Label {
                        text: "RECONCILIATION"
                        color: "#102a5e"
                        font.pixelSize: 17
                        font.bold: true
                    }
                    Label {
                        Layout.fillWidth: true
                        text: viewModel.reconciliationMessage || ""
                        color: "#58708c"
                        wrapMode: Text.Wrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Button {
                            text: viewModel.busy === true ? "CHECKING…" : "RECENT"
                            enabled: viewModel.canReconcile === true
                            onClicked: send("relay_reconcile_recent")
                        }
                        TextField {
                            id: monthField
                            Layout.preferredWidth: 130
                            text: viewModel.currentMonth || ""
                            placeholderText: "YYYY-MM"
                        }
                        Button {
                            text: "CHECK MONTH"
                            enabled: viewModel.canReconcile === true
                            onClicked: send("relay_reconcile_month", monthField.text)
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
        }
    }
}
