import QtQuick
import QtQuick.Controls

Rectangle {
    id: root
    objectName: "learningRoot"
    required property var controller
    required property var viewModel
    property string screen: viewModel.screen || "profiles"
    property var colors: ["#35a99a", "#4e7dcc", "#e58b5f", "#8a6dc1", "#d26483", "#69a94f"]

    anchors.fill: parent
    color: "#eef9f7"

    function send(action, value) {
        controller.requestViewAction(action, value === undefined ? "" : String(value))
    }

    function colorAt(index) {
        return colors[Math.abs(index) % colors.length]
    }

    gradient: Gradient {
        GradientStop { position: 0.0; color: "#e6f8f6" }
        GradientStop { position: 0.72; color: "#f5fbf2" }
        GradientStop { position: 1.0; color: "#fff7dd" }
    }

    // Quiet, programmatic decoration keeps the surface friendly without
    // competing with lesson content or requiring additional artwork.
    Rectangle { x: -28; y: 250; width: 110; height: 110; radius: 55; color: "#5bc9c2"; opacity: 0.10 }
    Rectangle { x: 730; y: 294; width: 96; height: 96; radius: 26; rotation: 18; color: "#f2c84b"; opacity: 0.13 }
    Rectangle { x: 642; y: 18; width: 18; height: 18; radius: 5; rotation: 45; color: "#f08aa6"; opacity: 0.24 }
    Rectangle { x: 112; y: 24; width: 12; height: 12; radius: 6; color: "#4e7dcc"; opacity: 0.18 }

    component KidButton: Rectangle {
        id: button
        required property string label
        property color baseColor: "#3978c3"
        property color textColor: "white"
        property int textSize: 15
        property bool outlined: false
        signal clicked()

        radius: Math.min(14, height / 4)
        color: !enabled ? "#c7d3d8" : (tap.pressed ? Qt.darker(baseColor, 1.12) : (outlined ? "#ffffff" : baseColor))
        border.color: !enabled ? "#aab9bf" : (outlined ? baseColor : Qt.darker(baseColor, 1.16))
        border.width: 2
        scale: tap.pressed && enabled ? 0.98 : 1.0

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 4
            height: 4
            radius: 2
            color: "white"
            opacity: button.outlined || !button.enabled ? 0.0 : 0.18
        }

        Label {
            anchors.fill: parent
            anchors.margins: 8
            text: button.label
            color: button.outlined && button.enabled ? button.baseColor : button.textColor
            opacity: button.enabled ? 1.0 : 0.72
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.Wrap
            elide: Text.ElideRight
            maximumLineCount: 2
            font.pixelSize: button.textSize
            font.bold: true
        }

        TapHandler {
            id: tap
            enabled: button.enabled
            onTapped: button.clicked()
        }

        Behavior on scale { NumberAnimation { duration: 70 } }
    }

    component PageHeading: Item {
        required property string title
        property string subtitle: ""
        property color accent: "#35a99a"
        height: subtitle ? 72 : 48

        Rectangle {
            x: 0
            y: 5
            width: 10
            height: parent.subtitle ? 55 : 34
            radius: 5
            color: parent.accent
        }
        Label {
            x: 24
            y: 0
            width: parent.width - 24
            height: 38
            text: parent.title
            color: "#102a5e"
            font.pixelSize: 27
            font.bold: true
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
        Label {
            x: 24
            y: 39
            width: parent.width - 24
            height: 26
            visible: parent.subtitle !== ""
            text: parent.subtitle
            color: "#58708c"
            font.pixelSize: 14
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }
    }

    component EmptyCard: Rectangle {
        required property string message
        color: "#ffffffcc"
        radius: 16
        border.color: "#bad6dd"
        border.width: 2
        Label {
            anchors.centerIn: parent
            width: parent.width - 36
            text: parent.message
            color: "#58708c"
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            font.pixelSize: 16
            font.bold: true
        }
    }

    Item {
        id: profilesPage
        objectName: "learningProfilesPage"
        anchors.fill: parent
        visible: root.screen === "profiles"

        PageHeading {
            x: 36; y: 18; width: 728
            title: "Who is learning today?"
            subtitle: "Pick your name and let’s learn something new."
            accent: "#35a99a"
        }

        GridView {
            id: profileGrid
            objectName: "learningProfilesGrid"
            x: 35; y: 98; width: 730; height: 226
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            cellWidth: 243
            cellHeight: 78
            model: root.viewModel.profiles || []
            ScrollIndicator.vertical: ScrollIndicator {}

            delegate: KidButton {
                required property var modelData
                required property int index
                width: 229
                height: 66
                label: modelData.label
                baseColor: root.colorAt(index)
                textSize: 18
                onClicked: root.send("learning_profile", modelData.id)
            }
        }

        EmptyCard {
            x: 145; y: 120; width: 510; height: 145
            visible: (root.viewModel.profiles || []).length === 0
            message: "A teacher can add the first learner profile."
        }

        KidButton {
            x: 285; y: 342; width: 230; height: 58
            label: "TEACHER AREA"
            baseColor: "#5a6288"
            outlined: true
            onClicked: root.send("learning_teacher")
        }
    }

    Item {
        id: teacherPinPage
        objectName: "learningTeacherPinPage"
        anchors.fill: parent
        visible: root.screen === "teacher_pin"

        Rectangle {
            objectName: "learningPinPanel"
            x: 214; y: 8; width: 372; height: 402
            radius: 24
            color: "#ffffffed"
            border.color: "#8dcfc8"
            border.width: 3

            Label {
                x: 22; y: 16; width: 328; height: 34
                text: "Teacher access"
                color: "#102a5e"
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 24
                font.bold: true
            }
            Label {
                x: 22; y: 52; width: 328; height: 24
                text: "Enter the 4-digit PIN"
                color: "#58708c"
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 14
            }
            Rectangle {
                x: 76; y: 82; width: 220; height: 48
                radius: 14
                color: "#edf7ff"
                border.color: "#a7cbe1"
                Label {
                    anchors.centerIn: parent
                    text: root.viewModel.teacherPin || "○ ○ ○ ○"
                    color: "#2875bd"
                    font.pixelSize: 24
                    font.bold: true
                }
            }
            Grid {
                x: 41; y: 136
                columns: 3
                spacing: 7
                Repeater {
                    model: ["1","2","3","4","5","6","7","8","9"]
                    delegate: KidButton {
                        required property string modelData
                        width: 92; height: 48
                        label: modelData
                        baseColor: "#3978c3"
                        textSize: 19
                        onClicked: root.send("learning_teacher_digit", modelData)
                    }
                }
                KidButton { width: 92; height: 48; label: "CLEAR"; baseColor: "#d26a72"; textSize: 11; onClicked: root.send("learning_teacher_clear") }
                KidButton { width: 92; height: 48; label: "0"; baseColor: "#3978c3"; textSize: 19; onClicked: root.send("learning_teacher_digit", "0") }
                KidButton { width: 92; height: 48; label: "DELETE"; baseColor: "#5a6288"; textSize: 10; onClicked: root.send("learning_teacher_backspace") }
            }
            KidButton {
                x: 126; y: 354; width: 120; height: 36
                label: "CANCEL"
                baseColor: "#5a6288"
                outlined: true
                textSize: 10
                onClicked: root.send("learning_teacher_back")
            }
        }
    }

    Item {
        id: teacherHomePage
        objectName: "learningTeacherHomePage"
        anchors.fill: parent
        visible: root.screen === "teacher_home"

        PageHeading {
            x: 28; y: 12; width: 744
            title: "Teacher area"
            subtitle: "Choose a learner profile or add a new one."
            accent: "#8a6dc1"
        }

        GridView {
            id: teacherProfileGrid
            objectName: "learningTeacherProfilesGrid"
            x: 28; y: 88; width: 744; height: 232
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            cellWidth: 248
            cellHeight: 66
            model: root.viewModel.teacherProfiles || []
            ScrollIndicator.vertical: ScrollIndicator {}
            delegate: KidButton {
                required property var modelData
                required property int index
                width: 234; height: 56
                label: modelData.label + (modelData.archived ? "\nARCHIVED" : "")
                baseColor: modelData.archived ? "#89969d" : root.colorAt(index + 1)
                textSize: modelData.archived ? 13 : 16
                onClicked: root.send("learning_teacher_profile", modelData.id)
            }
        }

        EmptyCard {
            x: 145; y: 105; width: 510; height: 135
            visible: (root.viewModel.teacherProfiles || []).length === 0
            message: "No learner profiles yet. Add one below to get started."
        }

        KidButton {
            x: 166; y: 340; width: 220; height: 58
            label: "ADD LEARNER"
            baseColor: "#35a06f"
            enabled: !root.viewModel.readOnly
            onClicked: root.send("learning_text_open", "new_profile")
        }
        KidButton {
            x: 414; y: 340; width: 220; height: 58
            label: "EXIT TEACHER"
            baseColor: "#5a6288"
            outlined: true
            textSize: 13
            onClicked: root.send("learning_teacher_back")
        }
    }

    Item {
        id: teacherProfilePage
        objectName: "learningTeacherProfilePage"
        anchors.fill: parent
        visible: root.screen === "teacher_profile"

        PageHeading {
            x: 28; y: 8; width: 744
            title: "Learner: " + (root.viewModel.teacherProfileName || "")
            accent: "#4e7dcc"
        }

        KidButton {
            x: 28; y: 58; width: 210; height: 48
            label: "RENAME"
            baseColor: "#4e7dcc"
            textSize: 13
            enabled: !root.viewModel.readOnly && !root.viewModel.teacherProfileArchived
            onClicked: root.send("learning_text_open", "rename_profile")
        }
        KidButton {
            x: 250; y: 58; width: 210; height: 48
            label: "REPORT"
            baseColor: "#e58b5f"
            textSize: 13
            onClicked: root.send("learning_teacher_report")
        }
        KidButton {
            x: 612; y: 58; width: 160; height: 48
            label: "BACK"
            baseColor: "#5a6288"
            outlined: true
            textSize: 11
            onClicked: root.send("learning_teacher_back")
        }

        Label {
            x: 31; y: 112; width: 730; height: 24
            text: root.viewModel.teacherProfileArchived ? "ARCHIVED · RESTORE TO EDIT" : "LEARNING PLANS"
            color: root.viewModel.teacherProfileArchived ? "#a3424e" : "#58708c"
            font.pixelSize: 13
            font.bold: true
            font.letterSpacing: 1.0
        }

        GridView {
            id: teacherPlanGrid
            objectName: "learningTeacherPlansGrid"
            x: 28; y: 140; width: 744; height: 150
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            cellWidth: 248
            cellHeight: 72
            model: root.viewModel.teacherPlans || []
            ScrollIndicator.vertical: ScrollIndicator {}
            delegate: KidButton {
                required property var modelData
                required property int index
                width: 234; height: 62
                label: modelData.label + (modelData.archived ? "\nARCHIVED" : (modelData.enabled ? "" : "\nPAUSED"))
                baseColor: modelData.archived || !modelData.enabled ? "#89969d" : root.colorAt(index)
                textSize: modelData.enabled && !modelData.archived ? 15 : 12
                onClicked: root.send("learning_teacher_plan", modelData.id)
            }
        }

        EmptyCard {
            x: 145; y: 143; width: 510; height: 126
            visible: (root.viewModel.teacherPlans || []).length === 0
            message: "No plans yet. Name a plan below to create one."
        }

        KidButton {
            x: 28; y: 310; width: 232; height: 58
            label: "NEW PLAN"
            baseColor: "#35a06f"
            enabled: !root.viewModel.readOnly && !root.viewModel.teacherProfileArchived
            onClicked: root.send("learning_text_open", "new_plan")
        }
        KidButton {
            x: 272; y: 310; width: 232; height: 58
            label: "RESET PROGRESS"
            baseColor: "#d26a72"
            textSize: 12
            enabled: !root.viewModel.readOnly
            onClicked: root.send("learning_reset_profile")
        }
        KidButton {
            x: 516; y: 310; width: 256; height: 58
            label: root.viewModel.teacherProfileArchived ? "RESTORE LEARNER" : "ARCHIVE LEARNER"
            baseColor: root.viewModel.teacherProfileArchived ? "#35a06f" : "#b84755"
            textSize: 12
            enabled: !root.viewModel.readOnly
            onClicked: {
                if (root.viewModel.teacherProfileArchived)
                    root.send("learning_restore_profile")
                else
                    root.send("learning_archive_profile")
            }
        }
    }

    Item {
        id: teacherPlanPage
        objectName: "learningTeacherPlanPage"
        anchors.fill: parent
        visible: root.screen === "teacher_plan"

        PageHeading {
            x: 28; y: 5; width: 744
            title: root.viewModel.teacherPlanName || "Learning plan"
            subtitle: (root.viewModel.teacherPlan || {}).archived ? "Archived plan" : "Plan settings and progress"
            accent: (root.viewModel.teacherPlan || {}).archived ? "#89969d" : "#35a99a"
        }

        Rectangle {
            objectName: "learningPlanCard"
            x: 28; y: 80; width: 744; height: 58
            radius: 15
            color: "#ffffffed"
            border.color: "#9ecbd4"
            border.width: 2
            Label {
                anchors.fill: parent
                anchors.margins: 8
                text: ((root.viewModel.teacherPlan || {}).lessons || 0) + " LESSONS   ·   "
                      + ((root.viewModel.teacherPlan || {}).questions || 0) + " QUESTIONS   ·   "
                      + ((root.viewModel.teacherPlan || {}).repetitions || 0) + " ROUNDS   ·   GATE "
                      + ((root.viewModel.teacherPlan || {}).masteryGate ? "ON" : "OFF")
                color: "#102a5e"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                font.pixelSize: 13
                font.bold: true
            }
        }

        Row {
            x: 28; y: 150; spacing: 10
            KidButton { width: 238; height: 54; label: "EDIT & REORDER"; baseColor: "#4e7dcc"; textSize: 12; enabled: !root.viewModel.readOnly && !(root.viewModel.teacherPlan || {}).archived; onClicked: root.send("learning_edit_plan") }
            KidButton { width: 238; height: 54; label: "DUPLICATE"; baseColor: "#35a99a"; textSize: 12; enabled: !root.viewModel.readOnly && !(root.viewModel.teacherPlan || {}).archived; onClicked: root.send("learning_duplicate_plan") }
            KidButton { width: 238; height: 54; label: (root.viewModel.teacherPlan || {}).enabled ? "TURN OFF" : "TURN ON"; baseColor: "#d09a2f"; textSize: 12; enabled: !root.viewModel.readOnly && !(root.viewModel.teacherPlan || {}).archived; onClicked: root.send("learning_toggle_plan") }
        }
        Row {
            x: 28; y: 214; spacing: 10
            KidButton { width: 238; height: 54; label: "VIEW REPORT"; baseColor: "#e58b5f"; textSize: 12; onClicked: root.send("learning_teacher_report") }
            KidButton { width: 238; height: 54; label: "RESET PROGRESS"; baseColor: "#d26a72"; textSize: 11; enabled: !root.viewModel.readOnly; onClicked: root.send("learning_reset_plan") }
            KidButton {
                width: 238; height: 54
                label: (root.viewModel.teacherPlan || {}).archived ? "RESTORE PLAN" : "ARCHIVE PLAN"
                baseColor: (root.viewModel.teacherPlan || {}).archived ? "#35a06f" : "#b84755"
                textSize: 11; enabled: !root.viewModel.readOnly
                onClicked: {
                    if ((root.viewModel.teacherPlan || {}).archived)
                        root.send("learning_restore_plan")
                    else
                        root.send("learning_archive_plan")
                }
            }
        }

        Rectangle {
            x: 55; y: 280; width: 690; height: 68
            radius: 14
            color: "#fff8dd"
            border.color: "#e2c562"
            Label {
                anchors.fill: parent
                anchors.margins: 9
                text: "MASTERY GATE: ON introduces foundation lessons first and unlocks later lessons after enough accurate practice. OFF makes the full plan available without erasing scores or changing its order."
                color: "#6f5a16"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.Wrap
                font.pixelSize: 11
                font.bold: true
            }
        }
        KidButton {
            x: 310; y: 357; width: 180; height: 48
            label: "BACK"
            baseColor: "#5a6288"
            outlined: true
            textSize: 12
            onClicked: root.send("learning_teacher_back")
        }
    }

    Item {
        id: teacherPlanEditPage
        objectName: "learningTeacherPlanEditPage"
        anchors.fill: parent
        visible: root.screen === "teacher_plan_edit"

        PageHeading {
            x: 20; y: 2; width: 760
            title: "Edit: " + ((root.viewModel.planDraft || {}).name || "Learning plan")
            accent: "#4e7dcc"
        }

        KidButton {
            x: 18; y: 53; width: 170; height: 72
            label: "RENAME PLAN"
            baseColor: "#4e7dcc"
            textSize: 11
            enabled: !root.viewModel.readOnly
            onClicked: root.send("learning_text_open", "rename_plan")
        }
        Rectangle {
            x: 198; y: 53; width: 180; height: 72
            radius: 13; color: "#ffffffed"; border.color: "#9ecbd4"; border.width: 2
            Label { x: 42; y: 5; width: 96; height: 26; text: "QUESTIONS " + ((root.viewModel.planDraft || {}).questions || 0); color: "#102a5e"; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 11; font.bold: true }
            KidButton { x: 8; y: 34; width: 72; height: 30; label: "−"; baseColor: "#5a6288"; textSize: 17; enabled: !root.viewModel.readOnly; onClicked: root.send("learning_plan_adjust", "questions:-1") }
            KidButton { x: 100; y: 34; width: 72; height: 30; label: "+"; baseColor: "#35a06f"; textSize: 17; enabled: !root.viewModel.readOnly; onClicked: root.send("learning_plan_adjust", "questions:1") }
        }
        Rectangle {
            x: 388; y: 53; width: 180; height: 72
            radius: 13; color: "#ffffffed"; border.color: "#9ecbd4"; border.width: 2
            Label { x: 38; y: 5; width: 104; height: 26; text: "ROUNDS " + ((root.viewModel.planDraft || {}).repetitions || 0); color: "#102a5e"; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 11; font.bold: true }
            KidButton { x: 8; y: 34; width: 72; height: 30; label: "−"; baseColor: "#5a6288"; textSize: 17; enabled: !root.viewModel.readOnly; onClicked: root.send("learning_plan_adjust", "repetitions:-1") }
            KidButton { x: 100; y: 34; width: 72; height: 30; label: "+"; baseColor: "#35a06f"; textSize: 17; enabled: !root.viewModel.readOnly; onClicked: root.send("learning_plan_adjust", "repetitions:1") }
        }
        KidButton {
            x: 578; y: 53; width: 204; height: 72
            label: "MASTERY GATE\n" + ((root.viewModel.planDraft || {}).masteryGate ? "ON" : "OFF")
            baseColor: (root.viewModel.planDraft || {}).masteryGate ? "#35a06f" : "#89969d"
            textSize: 11
            enabled: !root.viewModel.readOnly
            onClicked: root.send("learning_plan_gate")
        }

        Label {
            x: 22; y: 131; width: 756; height: 22
            text: "ORDERED LESSONS · DRAG TO SCROLL"
            color: "#58708c"; font.pixelSize: 11; font.bold: true; font.letterSpacing: 0.8
        }
        ListView {
            id: planLessonList
            objectName: "learningPlanLessonList"
            x: 18; y: 154; width: 764; height: 186
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            spacing: 4
            model: root.viewModel.planDraftLessons || []
            ScrollIndicator.vertical: ScrollIndicator {}
            delegate: Rectangle {
                required property var modelData
                required property int index
                width: planLessonList.width - 10; height: 54; radius: 12
                color: index % 2 ? "#f5fbff" : "#ffffffed"
                border.color: "#a9c9d4"; border.width: 2
                Label {
                    x: 12; y: 5; width: 454; height: 44
                    text: (modelData.index + 1) + ". " + modelData.title + "\n" + modelData.domain.toUpperCase() + " · " + modelData.family.replace("_", " ").toUpperCase()
                    color: "#102a5e"; font.pixelSize: 11; font.bold: true
                    verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; maximumLineCount: 2
                }
                KidButton { x: 474; y: 8; width: 62; height: 38; label: "UP"; baseColor: "#4e7dcc"; textSize: 9; enabled: modelData.canMoveUp && !root.viewModel.readOnly; onClicked: root.send("learning_plan_move", modelData.index + ":-1") }
                KidButton { x: 544; y: 8; width: 68; height: 38; label: "DOWN"; baseColor: "#4e7dcc"; textSize: 8; enabled: modelData.canMoveDown && !root.viewModel.readOnly; onClicked: root.send("learning_plan_move", modelData.index + ":1") }
                KidButton { x: 620; y: 8; width: 122; height: 38; label: "REMOVE"; baseColor: "#d26a72"; textSize: 9; enabled: !root.viewModel.readOnly; onClicked: root.send("learning_plan_remove", modelData.id) }
            }
        }
        EmptyCard {
            x: 145; y: 174; width: 510; height: 132
            visible: (root.viewModel.planDraftLessons || []).length === 0
            message: "Choose at least one lesson. You can arrange the order here."
        }
        Row {
            x: 18; y: 350; spacing: 10
            KidButton { width: 244; height: 56; label: "CHOOSE LESSONS"; baseColor: "#35a99a"; textSize: 12; onClicked: root.send("learning_choose_lessons") }
            KidButton { width: 244; height: 56; label: "SAVE PLAN"; baseColor: "#35a06f"; textSize: 12; enabled: root.viewModel.readOnly !== true && (root.viewModel.planDraft || {}).saveReady === true; onClicked: root.send("learning_save_plan") }
            KidButton { width: 244; height: 56; label: "CANCEL"; baseColor: "#5a6288"; outlined: true; textSize: 12; onClicked: root.send("learning_cancel_plan") }
        }
    }

    Item {
        id: teacherLessonsPage
        objectName: "learningTeacherLessonsPage"
        anchors.fill: parent
        visible: root.screen === "teacher_lessons"

        PageHeading { x: 20; y: 2; width: 760; title: "Choose lessons"; accent: "#35a99a" }
        KidButton {
            x: 18; y: 53; width: 220; height: 50
            label: "DOMAIN\n" + (root.viewModel.lessonDomain || "all").replace("_", " ").toUpperCase()
            baseColor: "#4e7dcc"; textSize: 10
            onClicked: root.send("learning_lesson_filter", "domain")
        }
        KidButton {
            x: 248; y: 53; width: 220; height: 50
            label: "FAMILY\n" + (root.viewModel.lessonFamily || "all").replace("_", " ").toUpperCase()
            baseColor: "#8a6dc1"; textSize: 10
            onClicked: root.send("learning_lesson_filter", "family")
        }
        KidButton {
            x: 478; y: 53; width: 150; height: 50
            label: "ADD THESE\n" + (root.viewModel.lessonFilteredCount || 0)
            baseColor: "#35a06f"; textSize: 9
            enabled: !root.viewModel.readOnly && (root.viewModel.lessonFilteredCount || 0) > 0
            onClicked: root.send("learning_bulk_add_lessons")
        }
        KidButton {
            x: 638; y: 53; width: 144; height: 50
            label: "DONE"
            baseColor: "#5a6288"; outlined: true; textSize: 11
            onClicked: root.send("learning_teacher_back")
        }

        ListView {
            id: lessonCatalogList
            objectName: "learningLessonCatalog"
            x: 18; y: 112; width: 764; height: 294
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            spacing: 4
            model: root.viewModel.lessonChoices || []
            ScrollIndicator.vertical: ScrollIndicator {}
            delegate: KidButton {
                required property var modelData
                required property int index
                width: lessonCatalogList.width - 10; height: 54
                label: (modelData.selected ? "✓ ADDED   " : "+ ADD   ") + modelData.title + "\n" + modelData.domain.toUpperCase() + " · " + modelData.family.replace("_", " ").toUpperCase()
                baseColor: modelData.selected ? "#35a06f" : root.colorAt(index + 1)
                textSize: 10
                enabled: !root.viewModel.readOnly
                onClicked: root.send("learning_toggle_lesson", modelData.id)
            }
        }
    }

    Item {
        id: teacherLessonFilterPage
        objectName: "learningTeacherLessonFilterPage"
        anchors.fill: parent
        visible: root.screen === "teacher_lesson_filter"

        PageHeading { x: 55; y: 10; width: 690; title: root.viewModel.lessonFilterTitle || "Choose a filter"; accent: "#8a6dc1" }
        ListView {
            id: lessonFilterList
            objectName: "learningLessonFilterList"
            x: 90; y: 66; width: 620; height: 278
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            spacing: 5
            model: root.viewModel.lessonFilterValues || []
            ScrollIndicator.vertical: ScrollIndicator {}
            delegate: KidButton {
                required property var modelData
                width: lessonFilterList.width - 10; height: 52
                label: modelData.label
                baseColor: modelData.selected ? "#35a06f" : "#4e7dcc"
                textSize: 12
                onClicked: root.send("learning_set_lesson_filter", modelData.value)
            }
        }
        KidButton { x: 300; y: 356; width: 200; height: 50; label: "BACK"; baseColor: "#5a6288"; outlined: true; textSize: 11; onClicked: root.send("learning_teacher_back") }
    }

    Item {
        id: teacherTextPage
        objectName: "learningTeacherTextPage"
        anchors.fill: parent
        visible: root.screen === "teacher_text"

        PageHeading { x: 55; y: 2; width: 690; title: root.viewModel.textTitle || "Enter a name"; accent: "#4e7dcc" }
        Rectangle {
            x: 60; y: 51; width: 680; height: 46
            radius: 12; color: "white"; border.color: "#35a99a"; border.width: 3
            Label { anchors.fill: parent; anchors.margins: 7; text: root.viewModel.textValue || " "; color: "#102a5e"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideLeft; font.pixelSize: 18; font.bold: true }
        }
        GridView {
            id: learningNameKeyboard
            objectName: "learningNameKeyboard"
            x: 26; y: 105; width: 748; height: 212
            cellWidth: 74.8; cellHeight: 53
            interactive: false; clip: true
            model: root.viewModel.textKeys || []
            delegate: KidButton {
                required property string modelData
                required property int index
                width: 68; height: 46; label: modelData; baseColor: root.colorAt(index); textSize: 14
                onClicked: root.send("learning_text_key", modelData)
            }
        }
        Row {
            x: 70; y: 330; spacing: 10
            KidButton { width: 170; height: 66; label: "SPACE"; baseColor: "#35a99a"; textSize: 11; onClicked: root.send("learning_text_key", " ") }
            KidButton { width: 110; height: 66; label: "DELETE"; baseColor: "#d26a72"; textSize: 10; onClicked: root.send("learning_text_backspace") }
            KidButton { width: 100; height: 66; label: "CLEAR"; baseColor: "#b27731"; textSize: 10; onClicked: root.send("learning_text_clear") }
            KidButton { width: 120; height: 66; label: "CANCEL"; baseColor: "#5a6288"; outlined: true; textSize: 10; onClicked: root.send("learning_text_cancel") }
            KidButton { width: 160; height: 66; label: "SAVE"; baseColor: "#35a06f"; textSize: 12; enabled: root.viewModel.textCanSave === true && root.viewModel.readOnly !== true; onClicked: root.send("learning_text_save") }
        }
    }

    Item {
        id: teacherConfirmPage
        objectName: "learningTeacherConfirmPage"
        anchors.fill: parent
        visible: root.screen === "teacher_confirm"

        Rectangle {
            objectName: "learningConfirmationCard"
            x: 110; y: 48; width: 580; height: 300
            radius: 24; color: "#ffffffed"
            border.color: (root.viewModel.confirmation || {}).danger ? "#c45260" : "#d3ad3e"
            border.width: 4
            Label { x: 30; y: 25; width: 520; height: 45; text: (root.viewModel.confirmation || {}).title || "Please confirm"; color: "#102a5e"; horizontalAlignment: Text.AlignHCenter; font.pixelSize: 25; font.bold: true }
            Label { x: 42; y: 82; width: 496; height: 100; text: (root.viewModel.confirmation || {}).message || ""; color: "#58708c"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; wrapMode: Text.Wrap; font.pixelSize: 16; font.bold: true }
            Row {
                x: 48; y: 210; spacing: 20
                KidButton { width: 232; height: 62; label: "CANCEL"; baseColor: "#5a6288"; outlined: true; textSize: 12; onClicked: root.send("learning_confirm_cancel") }
                KidButton { width: 232; height: 62; label: (root.viewModel.confirmation || {}).label || "CONFIRM"; baseColor: (root.viewModel.confirmation || {}).danger ? "#b84755" : "#35a06f"; textSize: 11; enabled: !root.viewModel.readOnly; onClicked: root.send("learning_confirm") }
            }
        }
    }

    Item {
        id: teacherReportPage
        objectName: "learningTeacherReportPage"
        anchors.fill: parent
        visible: root.screen === "teacher_report"

        PageHeading {
            x: 28; y: 2; width: 744
            title: "Progress: " + ((root.viewModel.report || {}).title || "")
            accent: "#e58b5f"
        }

        GridView {
            objectName: "learningReportCards"
            x: 18; y: 54; width: 764; height: 158
            cellWidth: 191; cellHeight: 79
            interactive: false; clip: true
            model: (root.viewModel.report || {}).metrics || []
            delegate: Rectangle {
                required property var modelData
                width: 181; height: 70
                radius: 13; color: "#ffffffed"; border.color: modelData.color; border.width: 2
                Rectangle { x: 8; y: 7; width: 8; height: 56; radius: 4; color: modelData.color }
                Label { x: 22; y: 6; width: 150; height: 22; text: modelData.label; color: "#58708c"; horizontalAlignment: Text.AlignHCenter; font.bold: true; font.pixelSize: 10 }
                Label { x: 22; y: 27; width: 150; height: 36; text: modelData.value; color: "#102a5e"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 21; font.bold: true }
            }
        }
        Label { x: 30; y: 217; width: 740; height: 23; text: "SKILL MASTERY · DRAG TO SCROLL"; color: "#58708c"; font.pixelSize: 11; font.bold: true; font.letterSpacing: 0.8 }
        ListView {
            id: reportSkillList
            objectName: "learningReportSkillList"
            x: 30; y: 242; width: 740; height: 108
            clip: true; interactive: contentHeight > height; boundsBehavior: Flickable.StopAtBounds; spacing: 3
            model: (root.viewModel.report || {}).skills || []
            ScrollIndicator.vertical: ScrollIndicator {}
            delegate: Rectangle {
                required property var modelData
                width: reportSkillList.width - 10; height: 40; radius: 10
                color: "#ffffffdd"; border.color: "#bad6dd"
                Label { x: 12; y: 3; width: 470; height: 34; text: modelData.label; color: "#102a5e"; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; font.pixelSize: 11; font.bold: true }
                Label { x: 492; y: 3; width: 150; height: 34; text: modelData.status; color: modelData.status === "MASTERED" ? "#23805b" : "#7b5b25"; horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter; font.pixelSize: 10; font.bold: true }
                Label { x: 650; y: 3; width: 66; height: 34; text: modelData.grade; color: "#4e7dcc"; horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter; font.pixelSize: 12; font.bold: true }
            }
        }
        EmptyCard { x: 175; y: 247; width: 450; height: 90; visible: ((root.viewModel.report || {}).skills || []).length === 0; message: "No skill practice has been recorded yet." }
        KidButton {
            x: 310; y: 358; width: 180; height: 48
            label: "BACK"
            baseColor: "#5a6288"
            outlined: true
            onClicked: root.send("learning_teacher_back")
        }
    }

    Item {
        id: plansPage
        objectName: "learningPlansPage"
        anchors.fill: parent
        visible: root.screen === "plans"

        PageHeading {
            x: 36; y: 16; width: 728
            title: "Hello, " + (root.viewModel.profileName || "Learner") + "!"
            subtitle: "Choose a learning plan or jump into quick practice."
            accent: "#f0a34f"
        }

        GridView {
            id: learnerPlanGrid
            objectName: "learningPlansGrid"
            x: 35; y: 98; width: 730; height: 218
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            cellWidth: 243
            cellHeight: 82
            model: root.viewModel.plans || []
            ScrollIndicator.vertical: ScrollIndicator {}
            delegate: KidButton {
                required property var modelData
                required property int index
                width: 229; height: 70
                label: modelData.label + "\n" + modelData.lessons + (modelData.lessons === 1 ? " LESSON" : " LESSONS")
                baseColor: root.colorAt(index + 2)
                textSize: 14
                onClicked: root.send("learning_plan", modelData.id)
            }
        }

        EmptyCard {
            x: 145; y: 118; width: 510; height: 140
            visible: (root.viewModel.plans || []).length === 0
            message: "No active plans yet. Quick practice is ready anytime."
        }

        KidButton {
            x: 148; y: 338; width: 265; height: 60
            label: "QUICK PRACTICE"
            baseColor: "#35a06f"
            textSize: 16
            onClicked: root.send("learning_quick_start")
        }
        KidButton {
            x: 427; y: 338; width: 225; height: 60
            label: "CHANGE LEARNER"
            baseColor: "#5a6288"
            outlined: true
            textSize: 14
            onClicked: root.send("learning_home")
        }
    }

    Item {
        id: lessonPage
        objectName: "learningLessonPage"
        anchors.fill: parent
        visible: root.screen === "lesson"

        Rectangle {
            x: 22; y: 12; width: 128; height: 40
            radius: 20
            color: "#ffffffdd"
            border.color: "#9ecbd4"
            border.width: 2
            Label { anchors.centerIn: parent; text: root.viewModel.progress || ""; color: "#58708c"; font.pixelSize: 14; font.bold: true }
        }
        KidButton {
            x: 628; y: 8; width: 150; height: 48
            label: "HEAR AGAIN"
            baseColor: "#d26483"
            textSize: 12
            enabled: root.viewModel.canAnnounce === true
            onClicked: root.send("learning_replay")
        }
        Label {
            objectName: "learningPrompt"
            x: 155; y: 5; width: 468; height: 62
            text: root.viewModel.prompt || ""
            color: "#102a5e"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.Wrap
            maximumLineCount: 2
            font.pixelSize: 23
            font.bold: true
        }

        GridView {
            id: choiceGrid
            objectName: "learningLessonChoices"
            property int choiceCount: (root.viewModel.choices || []).length
            property int columns: choiceCount <= 4 ? 2 : (choiceCount <= 10 ? 5 : 9)
            x: 31; y: 78; width: 738
            height: 250
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            cellWidth: width / columns
            cellHeight: choiceCount <= 4 ? 116 : (choiceCount <= 10 ? 92 : 74)
            model: root.viewModel.choices || []
            ScrollIndicator.vertical: ScrollIndicator {}

            delegate: Rectangle {
                required property var modelData
                width: choiceGrid.cellWidth - 10
                height: choiceGrid.cellHeight - 10
                radius: choiceGrid.choiceCount > 10 ? 12 : 17
                color: modelData.selected === true || (modelData.assignment || "") !== "" ? "#ffe28a" : "#ffffffed"
                border.color: modelData.selected === true || (modelData.assignment || "") !== "" ? "#d3981c" : "#8db7c6"
                border.width: modelData.selected === true || (modelData.assignment || "") !== "" ? 4 : 2

                Label {
                    anchors.fill: parent
                    anchors.margins: 6
                    text: (modelData.order ? modelData.order + ". " : "") + modelData.label + (modelData.assignment ? "\n→ " + modelData.assignment : "")
                    color: "#102a5e"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.Wrap
                    maximumLineCount: 3
                    font.pixelSize: choiceGrid.choiceCount > 10 ? 18 : (choiceGrid.choiceCount > 4 ? 17 : 22)
                    font.bold: true
                }
                TapHandler { onTapped: root.send("learning_choice", modelData.id) }
            }
        }

        KidButton {
            x: 22; y: 352; width: 150; height: 52
            label: "END LESSON"
            baseColor: "#5a6288"
            outlined: true
            textSize: 12
            onClicked: root.send("learning_back")
        }
        KidButton {
            x: 286; y: 344; width: 228; height: 62
            visible: root.viewModel.requiresSubmit === true
            enabled: root.viewModel.submitReady === true
            label: "CHECK ANSWER"
            baseColor: "#35a06f"
            textSize: 15
            onClicked: root.send("learning_submit")
        }
    }

    Item {
        id: feedbackPage
        objectName: "learningFeedbackPage"
        anchors.fill: parent
        visible: root.screen === "feedback"

        Rectangle {
            objectName: "learningFeedbackBadge"
            x: 316; y: 28; width: 168; height: 168
            radius: 84
            color: root.viewModel.tryAgain ? "#ffe08a" : "#69b982"
            border.color: root.viewModel.tryAgain ? "#d59a21" : "#32815a"
            border.width: 5
            Label {
                anchors.centerIn: parent
                text: root.viewModel.tryAgain ? "KEEP\nTRYING" : "NICE\nWORK!"
                color: root.viewModel.tryAgain ? "#704d0c" : "white"
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 24
                font.bold: true
            }
        }
        Label {
            x: 90; y: 218; width: 620; height: 86
            text: root.viewModel.feedback || ""
            color: "#102a5e"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.Wrap
            maximumLineCount: 3
            font.pixelSize: 21
            font.bold: true
        }
        KidButton {
            x: 270; y: 326; width: 260; height: 66
            label: root.viewModel.tryAgain ? "TRY AGAIN" : "CONTINUE"
            baseColor: root.viewModel.tryAgain ? "#e58b5f" : "#35a06f"
            textSize: 17
            onClicked: root.send("learning_continue")
        }
    }

    Item {
        id: completePage
        objectName: "learningCompletePage"
        anchors.fill: parent
        visible: root.screen === "complete"

        Row {
            x: 254; y: 62
            spacing: 24
            Repeater {
                model: ["#f2c84b", "#f08aa6", "#5bc9c2"]
                delegate: Label {
                    required property string modelData
                    width: 82; height: 82
                    text: "★"
                    color: modelData
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font.pixelSize: 62
                }
            }
        }
        Label {
            x: 100; y: 165; width: 600; height: 66
            text: "Great practice!"
            color: "#23805b"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: 38
            font.bold: true
        }
        Label {
            x: 150; y: 232; width: 500; height: 40
            text: "You kept going and helped your brain grow."
            color: "#58708c"
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            font.pixelSize: 17
        }
        KidButton {
            x: 260; y: 306; width: 280; height: 68
            label: "BACK TO LEARNING"
            baseColor: "#35a06f"
            textSize: 16
            onClicked: root.send("learning_back")
        }
    }

    Rectangle {
        id: errorBanner
        objectName: "learningErrorBanner"
        x: 135; y: 8; width: 530; height: 46
        z: 20
        visible: (root.viewModel.error || "") !== ""
        radius: 14
        color: "#fff2f1"
        border.color: "#c94e58"
        border.width: 2
        Label {
            anchors.fill: parent
            anchors.margins: 9
            text: root.viewModel.error || ""
            color: "#9d2835"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.Wrap
            maximumLineCount: 2
            font.pixelSize: 13
            font.bold: true
        }
    }
}
