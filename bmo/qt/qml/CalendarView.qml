import QtQuick
import QtQuick.Controls.Basic

Item {
    id: root
    objectName: "calendarRoot"
    required property var controller
    required property var viewModel

    readonly property color navy: "#102a5e"
    readonly property color ink: "#173653"
    readonly property color muted: "#58708c"
    readonly property color teal: "#16847d"
    readonly property color blue: "#1578d3"
    readonly property color coral: "#d9545d"
    readonly property color gold: "#e0a800"
    readonly property bool showingCalendar: ["day", "month", "year"].indexOf(viewModel.mode || "day") >= 0

    function send(action, value) {
        controller.requestViewAction(action, value === undefined ? "" : String(value))
    }

    component CalendarButton: Rectangle {
        id: button
        property string label: ""
        property color fillColor: root.navy
        property color textColor: "white"
        property bool selected: false
        signal clicked()
        radius: 11
        color: !enabled ? "#d6e1e8" : (tap.pressed ? Qt.darker(fillColor, 1.12) : fillColor)
        border.color: selected ? "#f5c84c" : (enabled ? Qt.darker(fillColor, 1.18) : "#bdcbd4")
        border.width: selected ? 3 : 1
        opacity: enabled ? 1 : 0.72

        Label {
            anchors.centerIn: parent
            width: parent.width - 10
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            text: button.label
            color: button.enabled ? button.textColor : "#78909c"
            font.pixelSize: 12
            font.bold: true
        }

        MouseArea {
            id: tap
            anchors.fill: parent
            enabled: button.enabled
            onClicked: button.clicked()
        }
    }

    component CalendarField: TextField {
        height: 40
        color: root.ink
        placeholderTextColor: "#8296a7"
        selectionColor: root.blue
        selectedTextColor: "white"
        font.pixelSize: 14
        leftPadding: 11
        rightPadding: 11
        background: Rectangle {
            radius: 9
            color: parent.enabled ? "white" : "#e9eff2"
            border.color: parent.activeFocus ? root.blue : "#abc5d3"
            border.width: parent.activeFocus ? 2 : 1
        }
    }

    component CalendarCombo: ComboBox {
        height: 40
        font.pixelSize: 14
        leftPadding: 11
        rightPadding: 30
        contentItem: Label {
            leftPadding: 3
            verticalAlignment: Text.AlignVCenter
            text: parent.displayText
            color: root.ink
            font.pixelSize: 14
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 9
            color: "white"
            border.color: parent.activeFocus ? root.blue : "#abc5d3"
            border.width: parent.activeFocus ? 2 : 1
        }
    }

    component FieldTitle: Label {
        color: root.muted
        font.pixelSize: 11
        font.bold: true
        font.letterSpacing: 0.7
    }

    Rectangle {
        anchors.fill: parent
        color: "#e9f8f7"
    }

    Rectangle {
        x: -32; y: 265; width: 118; height: 118; radius: 59
        color: "#58c7bb"; opacity: 0.11
    }
    Rectangle {
        x: 708; y: 260; width: 135; height: 135; radius: 68
        color: "#f3ca4d"; opacity: 0.12
    }
    Rectangle {
        x: 625; y: 85; width: 36; height: 36; radius: 18
        color: "#d9545d"; opacity: 0.08
    }

    Row {
        id: navigation
        visible: root.showingCalendar
        x: 13
        y: 9
        height: 44
        spacing: 6

        CalendarButton {
            width: 70; height: 44
            label: "TODAY"
            fillColor: root.teal
            onClicked: root.send("calendar_today")
        }
        CalendarButton {
            width: 64; height: 44
            label: "DAY"
            fillColor: selected ? root.blue : "#31526e"
            selected: root.viewModel.mode === "day"
            onClicked: root.send("calendar_show_day")
        }
        CalendarButton {
            width: 72; height: 44
            label: "MONTH"
            fillColor: selected ? root.blue : "#31526e"
            selected: root.viewModel.mode === "month"
            onClicked: root.send("calendar_show_month")
        }
        CalendarButton {
            width: 64; height: 44
            label: "YEAR"
            fillColor: selected ? root.blue : "#31526e"
            selected: root.viewModel.mode === "year"
            onClicked: root.send("calendar_show_year")
        }
        CalendarButton {
            width: 42; height: 44
            label: "‹"
            fillColor: root.navy
            onClicked: root.send("calendar_previous")
        }
        Rectangle {
            width: 232
            height: 44
            radius: 12
            color: "#fbfeff"
            border.color: root.viewModel.accentColor || root.teal
            border.width: 2
            Label {
                anchors.fill: parent
                anchors.margins: 6
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
                text: (root.viewModel.navigationLabel || "").toUpperCase()
                color: root.ink
                font.pixelSize: 16
                font.bold: true
            }
        }
        CalendarButton {
            width: 42; height: 44
            label: "›"
            fillColor: root.navy
            onClicked: root.send("calendar_next")
        }
        CalendarButton {
            width: 86; height: 44
            label: "READ DAY"
            fillColor: "#7051b8"
            visible: root.viewModel.mode === "day"
            onClicked: root.send("calendar_announce")
        }
    }

    Item {
        id: dayView
        objectName: "calendarDayView"
        visible: root.viewModel.mode === "day"
        x: 13
        y: 58
        width: 774
        height: root.height - 110

        Rectangle {
            id: dateCard
            width: 154
            height: parent.height
            radius: 16
            color: root.viewModel.accentColor || root.teal
            border.color: "white"
            border.width: 2

            Column {
                anchors.centerIn: parent
                width: parent.width - 16
                spacing: 4
                Label {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: (root.viewModel.dateLabel || "").split(",")[0].toUpperCase()
                    color: "white"
                    font.pixelSize: 14
                    font.bold: true
                }
                Label {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: Number((root.viewModel.date || "2000-01-01").slice(8, 10))
                    color: "white"
                    font.pixelSize: 58
                    font.bold: true
                }
                Label {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: root.viewModel.monthLabel || ""
                    color: "#fff5d6"
                    font.pixelSize: 15
                    font.bold: true
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 92; height: 3; radius: 2
                    color: "white"; opacity: 0.55
                }
                Label {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: (root.viewModel.events || []).length + ((root.viewModel.events || []).length === 1 ? " PLAN" : " PLANS")
                    color: "white"
                    font.pixelSize: 12
                    font.bold: true
                }
            }
        }

        ListView {
            id: dayEvents
            objectName: "calendarDayEvents"
            x: 166
            width: parent.width - x
            height: parent.height
            spacing: 7
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.viewModel.events || []

            delegate: Rectangle {
                id: eventRow
                required property var modelData
                width: ListView.view.width
                height: 64
                radius: 13
                color: root.viewModel.selectedId === modelData.id ? "#d9f2ff" : "#fbfeff"
                border.color: modelData.color || root.blue
                border.width: root.viewModel.selectedId === modelData.id ? 4 : 3

                Rectangle {
                    x: 10; anchors.verticalCenter: parent.verticalCenter
                    width: 13; height: 42; radius: 7
                    color: modelData.color || root.blue
                }
                Column {
                    x: 34
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 235
                    spacing: 2
                    Label {
                        width: parent.width
                        elide: Text.ElideRight
                        text: modelData.name
                        color: root.ink
                        font.pixelSize: 17
                        font.bold: true
                    }
                    Label {
                        width: parent.width
                        elide: Text.ElideRight
                        text: modelData.category + (modelData.notes ? "  •  " + modelData.notes : "")
                        color: root.muted
                        font.pixelSize: 11
                    }
                }
                Column {
                    anchors.right: parent.right
                    anchors.rightMargin: 14
                    anchors.verticalCenter: parent.verticalCenter
                    width: 180
                    spacing: 2
                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignRight
                        elide: Text.ElideRight
                        text: modelData.time
                        color: root.ink
                        font.pixelSize: 13
                        font.bold: true
                    }
                    Label {
                        width: parent.width
                        horizontalAlignment: Text.AlignRight
                        text: modelData.frequency !== "none" ? "↻ " + modelData.frequency.toUpperCase() : ""
                        color: "#7051b8"
                        font.pixelSize: 11
                        font.bold: true
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: root.send("calendar_select", modelData.id)
                }
            }

            Label {
                anchors.centerIn: parent
                visible: parent.count === 0
                text: "A wide-open day!\nAdd something fun to look forward to."
                horizontalAlignment: Text.AlignHCenter
                color: root.muted
                font.pixelSize: 17
                font.bold: true
            }

            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        }
    }

    Row {
        visible: root.viewModel.mode === "day"
        x: 13
        y: root.height - 46
        height: 40
        spacing: 8
        CalendarButton {
            width: 154; height: 40
            label: "+ ADD EVENT"
            fillColor: root.teal
            onClicked: root.send("calendar_add")
        }
        CalendarButton {
            width: 154; height: 40
            label: "EDIT SELECTED"
            fillColor: root.blue
            enabled: (root.viewModel.selectedId || "") !== "" && root.viewModel.selectedReadOnly !== true
            onClicked: root.send("calendar_edit")
        }
        CalendarButton {
            width: 144; height: 40
            label: "DELETE"
            fillColor: root.coral
            enabled: (root.viewModel.selectedId || "") !== "" && root.viewModel.selectedReadOnly !== true
            onClicked: root.send("calendar_request_delete")
        }
        Label {
            width: 290; height: 40
            horizontalAlignment: Text.AlignRight
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            text: (root.viewModel.selectedId || "") === "" ? "Tap an event to choose it" : (root.viewModel.selectedRecurring ? "Repeating event selected" : "Event selected")
            color: root.muted
            font.pixelSize: 12
            font.bold: true
        }
    }

    Item {
        id: monthView
        objectName: "calendarMonthView"
        visible: root.viewModel.mode === "month"
        x: 13
        y: 58
        width: 774
        height: root.height - 65

        Row {
            x: 0; y: 0; width: parent.width; height: 23
            Repeater {
                model: root.viewModel.weekdayLabels || []
                delegate: Label {
                    required property string modelData
                    width: monthView.width / 7
                    height: 23
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: modelData
                    color: root.muted
                    font.pixelSize: 11
                    font.bold: true
                }
            }
        }

        Item {
            id: monthGrid
            y: 24
            width: parent.width
            height: parent.height - 24
            property real cellWidth: width / 7
            property real cellHeight: height / 6

            Repeater {
                model: root.viewModel.monthDays || []
                delegate: Rectangle {
                    id: dayCell
                    required property var modelData
                    required property int index
                    property var dayData: modelData
                    x: (index % 7) * monthGrid.cellWidth
                    y: Math.floor(index / 7) * monthGrid.cellHeight
                    width: monthGrid.cellWidth - 2
                    height: monthGrid.cellHeight - 2
                    radius: 8
                    color: dayData.today ? "#fff0ad" : (dayData.inMonth ? "#fbfeff" : "#e7eff2")
                    border.color: dayData.selected ? root.blue : (dayData.today ? root.gold : "#bfd5df")
                    border.width: dayData.selected || dayData.today ? 3 : 1

                    Label {
                        x: 6; y: 3
                        text: dayCell.dayData.day
                        color: dayCell.dayData.inMonth ? root.ink : "#91a2ad"
                        font.pixelSize: 12
                        font.bold: dayCell.dayData.inMonth
                    }

                    Repeater {
                        model: dayCell.dayData.dots || []
                        delegate: Rectangle {
                            required property string modelData
                            required property int index
                            x: index < 4 ? 35 + index * 13 : 8 + (index - 4) * 13
                            y: index < 4 ? 7 : 27
                            width: 8; height: 8; radius: 4
                            color: modelData
                            border.color: "white"
                            border.width: 1
                        }
                    }
                    Label {
                        anchors.right: parent.right
                        anchors.rightMargin: 5
                        y: 24
                        visible: (dayCell.dayData.overflow || 0) > 0
                        text: "+" + dayCell.dayData.overflow
                        color: root.muted
                        font.pixelSize: 9
                        font.bold: true
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: root.send("calendar_open_date", dayCell.dayData.date)
                    }
                }
            }
        }
    }

    Item {
        id: yearView
        objectName: "calendarYearView"
        visible: root.viewModel.mode === "year"
        x: 13
        y: 60
        width: 774
        height: root.height - 68

        Grid {
            id: yearGrid
            anchors.fill: parent
            columns: 4
            rowSpacing: 8
            columnSpacing: 8

            Repeater {
                model: root.viewModel.yearMonths || []
                delegate: Rectangle {
                    id: monthCard
                    required property var modelData
                    width: (yearGrid.width - 24) / 4
                    height: (yearGrid.height - 16) / 3
                    radius: 15
                    color: modelData.color
                    border.color: modelData.current ? "#f8d866" : "white"
                    border.width: modelData.current ? 4 : 2

                    Rectangle {
                        x: 12; y: 10; width: 25; height: 25; radius: 13
                        color: "white"; opacity: 0.20
                    }
                    Label {
                        anchors.horizontalCenter: parent.horizontalCenter
                        y: 13
                        text: modelData.label
                        color: "white"
                        font.pixelSize: 19
                        font.bold: true
                    }
                    Label {
                        anchors.horizontalCenter: parent.horizontalCenter
                        y: 50
                        text: modelData.eventCount + (modelData.eventCount === 1 ? " EVENT" : " EVENTS")
                        color: "#fff8e8"
                        font.pixelSize: 11
                        font.bold: true
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: root.send("calendar_open_month", modelData.month)
                    }
                }
            }
        }
    }

    Item {
        id: editorView
        objectName: "calendarEditorView"
        visible: root.viewModel.mode === "editor"
        anchors.fill: parent
        property var editor: root.viewModel.editor || ({})
        property color selectedColor: "#1578d3"
        property real selectedHue: 0.58

        function weekdaySelected(day) {
            return (editor.weekdays || []).indexOf(day) >= 0
        }
        function selectedWeekdays() {
            let values = []
            if (monday.checked) values.push(0)
            if (tuesday.checked) values.push(1)
            if (wednesday.checked) values.push(2)
            if (thursday.checked) values.push(3)
            if (friday.checked) values.push(4)
            if (saturday.checked) values.push(5)
            if (sunday.checked) values.push(6)
            return values
        }
        function resetFields() {
            calendarName.text = editor.name || ""
            calendarDate.text = editor.date || ""
            calendarAllDay.checked = editor.allDay !== false
            calendarStart.text = editor.startTime || "09:00"
            calendarEnd.text = editor.endTime || "10:00"
            calendarRepeat.currentIndex = Math.max(0, calendarRepeat.indexOfValue(editor.frequency || "none"))
            calendarCategory.currentIndex = Math.max(0, calendarCategory.model.indexOf(editor.category || ""))
            repeatEnd.currentIndex = Math.max(0, repeatEnd.indexOfValue(editor.repeatEndKind || "never"))
            repeatEndValue.text = editor.repeatEndValue || ""
            monthlyOverflow.currentIndex = Math.max(0, monthlyOverflow.indexOfValue(editor.monthlyOverflow || "last_day"))
            calendarNotes.text = editor.notes || ""
            selectedColor = editor.color || "#1578d3"
            monday.checked = weekdaySelected(0)
            tuesday.checked = weekdaySelected(1)
            wednesday.checked = weekdaySelected(2)
            thursday.checked = weekdaySelected(3)
            friday.checked = weekdaySelected(4)
            saturday.checked = weekdaySelected(5)
            sunday.checked = weekdaySelected(6)
        }
        function save() {
            root.send("calendar_request_save", JSON.stringify({
                name: calendarName.text,
                date: calendarDate.text,
                allDay: calendarAllDay.checked,
                startTime: calendarStart.text,
                endTime: calendarEnd.text,
                category: calendarCategory.currentText,
                color: String(selectedColor),
                notes: calendarNotes.text,
                frequency: calendarRepeat.currentValue,
                weekdays: selectedWeekdays(),
                repeatEndKind: repeatEnd.currentValue,
                repeatEndValue: repeatEndValue.text,
                monthlyOverflow: monthlyOverflow.currentValue
            }))
        }
        onVisibleChanged: if (visible) Qt.callLater(resetFields)
        onEditorChanged: if (visible) Qt.callLater(resetFields)

        Rectangle {
            x: 13; y: 9; width: 774; height: 44; radius: 13
            color: root.navy
            Label {
                x: 15; anchors.verticalCenter: parent.verticalCenter
                text: editorView.editor.editing ? "EDIT THIS PLAN" : "ADD A HAPPY PLAN"
                color: "white"
                font.pixelSize: 17
                font.bold: true
            }
            Label {
                x: 205; anchors.verticalCenter: parent.verticalCenter
                width: 420
                horizontalAlignment: Text.AlignHCenter
                text: "Swipe up for every option"
                color: "#c7e9ef"
                font.pixelSize: 12
                font.bold: true
            }
            CalendarButton {
                anchors.right: parent.right; anchors.rightMargin: 7
                anchors.verticalCenter: parent.verticalCenter
                width: 105; height: 34
                label: "CANCEL"
                fillColor: root.coral
                onClicked: root.send("calendar_cancel_edit")
            }
        }

        Flickable {
            id: editorFlick
            objectName: "calendarEditorFlick"
            x: 13; y: 58
            width: 774; height: root.height - 64
            contentWidth: width
            contentHeight: 530
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Item {
                width: editorFlick.width
                height: editorFlick.contentHeight

                Rectangle {
                    x: 0; y: 0; width: 378; height: 412; radius: 16
                    color: "#fbfeff"; border.color: "#b6d5df"; border.width: 2

                    FieldTitle { x: 14; y: 13; text: "EVENT NAME" }
                    CalendarField { id: calendarName; x: 14; y: 34; width: 350; placeholderText: "What is happening?" }
                    FieldTitle { x: 14; y: 83; text: "DATE (YYYY-MM-DD)" }
                    CalendarField { id: calendarDate; x: 14; y: 103; width: 190; placeholderText: "YYYY-MM-DD" }
                    CheckBox {
                        id: calendarAllDay
                        x: 220; y: 101; height: 42
                        text: "All day"
                        checked: true
                        palette.windowText: root.ink
                        font.pixelSize: 14
                        font.bold: true
                    }
                    FieldTitle { x: 14; y: 153; text: "FROM" }
                    FieldTitle { x: 197; y: 153; text: "TO" }
                    CalendarField { id: calendarStart; x: 14; y: 173; width: 166; enabled: !calendarAllDay.checked }
                    CalendarField { id: calendarEnd; x: 197; y: 173; width: 167; enabled: !calendarAllDay.checked }
                    FieldTitle { x: 14; y: 222; text: "CATEGORY" }
                    CalendarCombo { id: calendarCategory; x: 14; y: 242; width: 350; model: root.viewModel.categories || [] }
                    FieldTitle { x: 14; y: 291; text: "NOTES (NOT SPOKEN BY DEFAULT)" }
                    TextArea {
                        id: calendarNotes
                        x: 14; y: 312; width: 350; height: 85
                        wrapMode: TextEdit.Wrap
                        color: root.ink
                        font.pixelSize: 13
                        placeholderText: "Anything useful to remember?"
                        background: Rectangle { radius: 9; color: "white"; border.color: "#abc5d3" }
                    }
                }

                Rectangle {
                    x: 390; y: 0; width: 384; height: 462; radius: 16
                    color: "#fffdf7"; border.color: "#e5ca75"; border.width: 2

                    FieldTitle { x: 14; y: 13; text: "REPEAT" }
                    CalendarCombo {
                        id: calendarRepeat
                        x: 14; y: 34; width: 356
                        textRole: "label"; valueRole: "value"
                        model: [
                            { label: "Does not repeat", value: "none" },
                            { label: "Every week", value: "weekly" },
                            { label: "Every month", value: "monthly" },
                            { label: "Every year", value: "yearly" }
                        ]
                    }

                    Row {
                        x: 10; y: 82; spacing: 0
                        visible: calendarRepeat.currentValue === "weekly"
                        CheckBox { id: monday; width: 51; height: 38; text: "M"; font.pixelSize: 11 }
                        CheckBox { id: tuesday; width: 51; height: 38; text: "T"; font.pixelSize: 11 }
                        CheckBox { id: wednesday; width: 51; height: 38; text: "W"; font.pixelSize: 11 }
                        CheckBox { id: thursday; width: 51; height: 38; text: "T"; font.pixelSize: 11 }
                        CheckBox { id: friday; width: 51; height: 38; text: "F"; font.pixelSize: 11 }
                        CheckBox { id: saturday; width: 51; height: 38; text: "S"; font.pixelSize: 11 }
                        CheckBox { id: sunday; width: 51; height: 38; text: "S"; font.pixelSize: 11 }
                    }

                    FieldTitle { x: 14; y: 126; text: "REPEAT ENDS"; visible: calendarRepeat.currentValue !== "none" }
                    CalendarCombo {
                        id: repeatEnd
                        x: 14; y: 147; width: 165
                        textRole: "label"; valueRole: "value"
                        model: [
                            { label: "Never", value: "never" },
                            { label: "On a date", value: "date" },
                            { label: "After times", value: "count" }
                        ]
                        visible: calendarRepeat.currentValue !== "none"
                    }
                    CalendarField { id: repeatEndValue; x: 190; y: 147; width: 180; placeholderText: repeatEnd.currentValue === "date" ? "YYYY-MM-DD" : "Number of times"; visible: calendarRepeat.currentValue !== "none" && repeatEnd.currentValue !== "never" }

                    FieldTitle { x: 14; y: 196; text: "IF THIS DATE IS MISSING"; visible: calendarRepeat.currentValue === "monthly" }
                    CalendarCombo {
                        id: monthlyOverflow
                        x: 14; y: 217; width: 356
                        textRole: "label"; valueRole: "value"
                        model: [
                            { label: "Use the month's last day", value: "last_day" },
                            { label: "Skip that month", value: "skip" }
                        ]
                        visible: calendarRepeat.currentValue === "monthly"
                    }

                    FieldTitle { x: 14; y: 265; text: "CHOOSE A COLOR" }
                    Grid {
                        id: colorPicker
                        objectName: "calendarColorPicker"
                        x: 12; y: 284
                        columns: 6
                        rowSpacing: 3
                        columnSpacing: 3
                        Repeater {
                            model: root.viewModel.colorPalette || []
                            delegate: Item {
                                id: colorChoice
                                required property var modelData
                                width: 57; height: 54
                                Rectangle {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    y: 1; width: 31; height: 31; radius: 16
                                    color: modelData.color
                                    border.color: String(editorView.selectedColor).toUpperCase() === String(modelData.color).toUpperCase() ? root.gold : "white"
                                    border.width: String(editorView.selectedColor).toUpperCase() === String(modelData.color).toUpperCase() ? 4 : 2
                                }
                                Label {
                                    y: 35; width: parent.width
                                    horizontalAlignment: Text.AlignHCenter
                                    elide: Text.ElideRight
                                    text: modelData.name
                                    color: root.muted
                                    font.pixelSize: 8
                                    font.bold: true
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: editorView.selectedColor = modelData.color
                                }
                            }
                        }
                    }

                    FieldTitle { x: 14; y: 397; text: "MORE COLORS" }
                    Rectangle {
                        id: huePicker
                        objectName: "calendarHuePicker"
                        x: 14; y: 418; width: 356; height: 28; radius: 10
                        color: "white"
                        border.color: "white"; border.width: 2
                        clip: true
                        Row {
                            anchors.fill: parent
                            anchors.margins: 2
                            Repeater {
                                model: 60
                                Rectangle {
                                    required property int index
                                    width: (huePicker.width - 4) / 60
                                    height: huePicker.height - 4
                                    color: Qt.hsla(index / 59, 0.78, 0.48, 1.0)
                                }
                            }
                        }
                        function chooseColor(position) {
                            editorView.selectedHue = Math.max(0, Math.min(1, position / width))
                            editorView.selectedColor = Qt.hsla(editorView.selectedHue, 0.78, 0.48, 1.0)
                        }
                        MouseArea {
                            anchors.fill: parent
                            onPressed: function(mouse) { huePicker.chooseColor(mouse.x) }
                            onPositionChanged: function(mouse) {
                                if (pressed)
                                    huePicker.chooseColor(mouse.x)
                            }
                        }
                        Rectangle {
                            x: Math.max(2, Math.min(parent.width - width - 2, editorView.selectedHue * parent.width - width / 2))
                            anchors.verticalCenter: parent.verticalCenter
                            width: 12; height: 34; radius: 6
                            color: "transparent"
                            border.color: root.navy
                            border.width: 3
                        }
                    }

                }

                Row {
                    x: 0; y: 473; height: 46; spacing: 8
                    CalendarButton {
                        width: 178; height: 46
                        label: editorView.editor.editing ? "SAVE CHANGES" : "SAVE EVENT"
                        fillColor: root.teal
                        onClicked: editorView.save()
                    }
                    CalendarButton {
                        visible: editorView.editor.editing === true
                        width: 130; height: 46
                        label: "DELETE"
                        fillColor: root.coral
                        onClicked: root.send("calendar_request_delete")
                    }
                    CalendarButton {
                        width: 120; height: 46
                        label: "CANCEL"
                        fillColor: root.navy
                        onClicked: root.send("calendar_cancel_edit")
                    }
                    Label {
                        width: 320; height: 46
                        horizontalAlignment: Text.AlignRight
                        verticalAlignment: Text.AlignVCenter
                        text: "Repeating events ask what should change after Save."
                        color: root.muted
                        font.pixelSize: 11
                        font.bold: true
                        wrapMode: Text.Wrap
                    }
                }
            }
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        }
    }

    Rectangle {
        id: scopeDialog
        objectName: "calendarScopeDialog"
        visible: root.viewModel.mode === "scope"
        anchors.fill: parent
        color: "#99102a5e"
        z: 40

        Rectangle {
            anchors.centerIn: parent
            width: 540; height: 238; radius: 22
            color: "#fbfeff"
            border.color: root.gold
            border.width: 4

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                y: -19; width: 86; height: 38; radius: 19
                color: root.gold
                Label {
                    anchors.centerIn: parent
                    text: "BMO?"
                    color: root.navy
                    font.pixelSize: 16
                    font.bold: true
                }
            }
            Label {
                x: 28; y: 37; width: parent.width - 56; height: 74
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.Wrap
                text: root.viewModel.scopePrompt || "Apply this to one event or the whole series?"
                color: root.ink
                font.pixelSize: 18
                font.bold: true
            }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 127; spacing: 10
                CalendarButton {
                    width: 160; height: 52
                    label: "ONLY THIS ONE"
                    fillColor: root.blue
                    onClicked: root.send("calendar_scope", "occurrence")
                }
                CalendarButton {
                    width: 160; height: 52
                    label: "WHOLE SERIES"
                    fillColor: "#7051b8"
                    onClicked: root.send("calendar_scope", "series")
                }
                CalendarButton {
                    width: 100; height: 52
                    label: "CANCEL"
                    fillColor: root.coral
                    onClicked: root.send("calendar_scope_cancel")
                }
            }
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 195
                text: "Nothing changes until you choose."
                color: root.muted
                font.pixelSize: 11
                font.bold: true
            }
        }
    }

    Rectangle {
        visible: (root.viewModel.error || "") !== ""
        anchors.horizontalCenter: parent.horizontalCenter
        y: 54
        width: Math.min(640, errorText.implicitWidth + 38)
        height: 30
        radius: 15
        color: "#fff0ee"
        border.color: root.coral
        border.width: 2
        z: 60
        Label {
            id: errorText
            anchors.centerIn: parent
            text: root.viewModel.error || ""
            color: "#a33138"
            font.pixelSize: 12
            font.bold: true
        }
    }
}
