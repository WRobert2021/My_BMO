import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts

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

    component InputCard: Basic.TextField {
        color: "#102a5e"
        placeholderTextColor: "#75899c"
        font.pixelSize: 15
        leftPadding: 16
        rightPadding: 16
        selectByMouse: true
        background: Rectangle {
            radius: 12
            color: "white"
            border.color: parent.activeFocus ? "#35a99a" : "#a9c5cf"
            border.width: parent.activeFocus ? 3 : 2
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
            x: 214; y: 14; width: 372; height: 390
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
                x: 41; y: 142
                columns: 3
                spacing: 7
                Repeater {
                    model: ["1","2","3","4","5","6","7","8","9"]
                    delegate: KidButton {
                        required property string modelData
                        width: 92; height: 50
                        label: modelData
                        baseColor: "#3978c3"
                        textSize: 19
                        onClicked: root.send("learning_teacher_digit", modelData)
                    }
                }
                KidButton { width: 92; height: 50; label: "CLEAR"; baseColor: "#d26a72"; textSize: 11; onClicked: root.send("learning_teacher_clear") }
                KidButton { width: 92; height: 50; label: "0"; baseColor: "#3978c3"; textSize: 19; onClicked: root.send("learning_teacher_digit", "0") }
                KidButton { width: 92; height: 50; label: "BACK"; baseColor: "#5a6288"; textSize: 11; onClicked: root.send("learning_home") }
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
            x: 28; y: 88; width: 744; height: 196
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

        InputCard {
            id: newTeacherLearner
            x: 60; y: 300; width: 398; height: 52
            placeholderText: "New learner name"
        }
        KidButton {
            x: 470; y: 300; width: 210; height: 52
            label: "ADD LEARNER"
            baseColor: "#35a06f"
            enabled: !root.viewModel.readOnly
            onClicked: {
                root.send("learning_create_profile", newTeacherLearner.text)
                newTeacherLearner.clear()
            }
        }
        KidButton {
            x: 310; y: 363; width: 180; height: 44
            label: "EXIT TEACHER"
            baseColor: "#5a6288"
            outlined: true
            textSize: 12
            onClicked: root.send("learning_home")
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

        InputCard {
            id: renameTeacherLearner
            x: 28; y: 60; width: 335; height: 48
            placeholderText: "Rename learner"
        }
        KidButton {
            x: 375; y: 60; width: 140; height: 48
            label: "RENAME"
            baseColor: "#4e7dcc"
            textSize: 13
            enabled: !root.viewModel.readOnly
            onClicked: {
                root.send("learning_rename_profile", renameTeacherLearner.text)
                renameTeacherLearner.clear()
            }
        }
        KidButton {
            x: 527; y: 60; width: 140; height: 48
            label: "REPORT"
            baseColor: "#e58b5f"
            textSize: 13
            onClicked: root.send("learning_teacher_report")
        }
        KidButton {
            x: 679; y: 60; width: 93; height: 48
            label: "BACK"
            baseColor: "#5a6288"
            outlined: true
            textSize: 11
            onClicked: root.send("learning_teacher_back")
        }

        Label {
            x: 31; y: 119; width: 730; height: 24
            text: "LEARNING PLANS"
            color: "#58708c"
            font.pixelSize: 13
            font.bold: true
            font.letterSpacing: 1.0
        }

        GridView {
            id: teacherPlanGrid
            objectName: "learningTeacherPlansGrid"
            x: 28; y: 148; width: 744; height: 148
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
                label: modelData.label + (modelData.enabled ? "" : "\nPAUSED")
                baseColor: modelData.enabled ? root.colorAt(index) : "#89969d"
                textSize: modelData.enabled ? 15 : 12
                onClicked: root.send("learning_teacher_plan", modelData.id)
            }
        }

        EmptyCard {
            x: 145; y: 151; width: 510; height: 126
            visible: (root.viewModel.teacherPlans || []).length === 0
            message: "No plans yet. Name a plan below to create one."
        }

        InputCard {
            id: newLearningPlan
            x: 80; y: 315; width: 400; height: 54
            placeholderText: "New plan name"
        }
        KidButton {
            x: 492; y: 315; width: 228; height: 54
            label: "CREATE PLAN"
            baseColor: "#35a06f"
            enabled: !root.viewModel.readOnly
            onClicked: {
                root.send("learning_create_plan", newLearningPlan.text)
                newLearningPlan.clear()
            }
        }
    }

    Item {
        id: teacherPlanPage
        objectName: "learningTeacherPlanPage"
        anchors.fill: parent
        visible: root.screen === "teacher_plan"

        Rectangle {
            objectName: "learningPlanCard"
            x: 90; y: 40; width: 620; height: 300
            radius: 24
            color: "#ffffffed"
            border.color: "#9ecbd4"
            border.width: 3

            Rectangle { x: 0; y: 0; width: 18; height: parent.height; radius: 9; color: "#35a99a" }
            Rectangle { x: 36; y: 28; width: 48; height: 48; radius: 24; color: "#fff1b8"; border.color: "#efc64c"; border.width: 2
                Label { anchors.centerIn: parent; text: "★"; color: "#c88b16"; font.pixelSize: 26 }
            }
            Label {
                x: 102; y: 24; width: 475; height: 54
                text: root.viewModel.teacherPlanName || "Learning plan"
                color: "#102a5e"
                font.pixelSize: 28
                font.bold: true
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
            Label {
                x: 42; y: 96; width: 536; height: 54
                text: "This plan uses the validated Pre-K lesson catalog. You can pause it or open its progress report."
                color: "#58708c"
                font.pixelSize: 16
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.Wrap
            }
            Row {
                x: 42; y: 182
                spacing: 12
                KidButton { width: 190; height: 62; label: "ENABLE / DISABLE"; baseColor: "#4e7dcc"; textSize: 13; enabled: !root.viewModel.readOnly; onClicked: root.send("learning_toggle_plan") }
                KidButton { width: 170; height: 62; label: "VIEW REPORT"; baseColor: "#e58b5f"; textSize: 13; onClicked: root.send("learning_teacher_report") }
                KidButton { width: 130; height: 62; label: "BACK"; baseColor: "#5a6288"; outlined: true; textSize: 12; onClicked: root.send("learning_teacher_back") }
            }
        }
    }

    Item {
        id: teacherReportPage
        objectName: "learningTeacherReportPage"
        anchors.fill: parent
        visible: root.screen === "teacher_report"

        PageHeading {
            x: 55; y: 18; width: 690
            title: "Progress: " + ((root.viewModel.report || {}).title || "")
            subtitle: "A clear snapshot of recent learning."
            accent: "#e58b5f"
        }

        Row {
            objectName: "learningReportCards"
            x: 55; y: 112
            spacing: 12
            Repeater {
                model: [
                    {label:"GRADE", value:(root.viewModel.report || {}).grade || "0%", color:"#4e7dcc"},
                    {label:"COMPLETE", value:(root.viewModel.report || {}).completion || "0%", color:"#35a99a"},
                    {label:"ATTEMPTS", value:(root.viewModel.report || {}).attempts || 0, color:"#8a6dc1"},
                    {label:"RECENT", value:(root.viewModel.report || {}).recent || "0%", color:"#e58b5f"}
                ]
                delegate: Rectangle {
                    required property var modelData
                    width: 164; height: 142
                    radius: 18
                    color: "#ffffffed"
                    border.color: modelData.color
                    border.width: 3
                    Rectangle { x: 10; y: 10; width: 144; height: 12; radius: 6; color: modelData.color; opacity: 0.78 }
                    Label { x: 10; y: 36; width: 144; height: 25; text: modelData.label; color: "#58708c"; horizontalAlignment: Text.AlignHCenter; font.bold: true; font.pixelSize: 12 }
                    Label { x: 10; y: 67; width: 144; height: 52; text: modelData.value; color: "#102a5e"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 27; font.bold: true }
                }
            }
        }
        KidButton {
            x: 310; y: 320; width: 180; height: 58
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
