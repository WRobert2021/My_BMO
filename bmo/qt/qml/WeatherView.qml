import QtQuick
import QtQuick.Controls

Item {
    id: root
    required property var controller
    required property var viewModel
    property var model: viewModel || ({})
    property real uiScale: Math.min(width / 800, height / 480)
    property bool debugOpen: false
    property bool debugActive: false
    property string debugCondition: "sunny"
    property string debugSeason: "summer"
    property string debugTime: "morning"
    property string debugPhase: "full"
    property real swipeDx: 0
    property real swipeDy: 0

    property var conditions: [
        ["sunny", "Sunny"], ["mostly-clear", "Mostly clear"],
        ["partly", "Partly cloudy"], ["cloudy", "Cloudy"],
        ["overcast", "Overcast"], ["fog", "Fog"],
        ["drizzle", "Drizzle"], ["rain", "Rain"],
        ["heavy-rain", "Heavy rain"], ["freezing-rain", "Freezing rain"],
        ["storm", "Thunderstorm"], ["snow", "Snow"],
        ["heavy-snow", "Heavy snow"], ["sleet", "Sleet / ice"],
        ["hail", "Hail"], ["wind", "High wind"],
        ["hot", "Very hot"], ["cold", "Very cold"],
        ["mixed", "Mixed"], ["severe", "Safety alert"]
    ]
    property var seasons: [["spring", "Spring"], ["summer", "Summer"], ["fall", "Fall"], ["winter", "Winter"], ["neutral", "Season off"]]
    property var times: [["morning", "Morning"], ["midday", "Midday"], ["afternoon", "Afternoon"], ["sunset", "Sunset"], ["night", "Night"]]
    property var phases: [["full", "Full"], ["new", "New"], ["waxing-crescent", "Waxing crescent"], ["first-quarter", "First quarter"], ["waxing-gibbous", "Waxing gibbous"], ["waning-gibbous", "Waning gibbous"], ["last-quarter", "Last quarter"], ["waning-crescent", "Waning crescent"]]

    readonly property bool ready: model.status === "ready"
    readonly property string shownCondition: debugActive ? debugCondition : (model.condition || "sunny")
    readonly property string shownSeason: debugActive ? debugSeason : (model.season || "neutral")
    readonly property string shownTime: debugActive ? debugTime : (model.time || "morning")
    readonly property string shownPhase: debugActive ? debugPhase : (model.phase || "full")
    readonly property bool darkText: shownTime !== "night" && shownCondition !== "storm" && shownCondition !== "severe"
    readonly property color readoutColor: darkText ? "#123e38" : "#fffce5"
    readonly property var shownPreview: previewFor(shownCondition)
    readonly property var shownHours: ready && !debugActive ? (model.hours || []) : shownPreview.hours

    function send(action, value) {
        controller.requestViewAction(action, value === undefined ? "" : String(value))
    }

    function speak(key) {
        if (ready && !debugActive && model.speech_available === true)
            send("weather_speak", key)
    }

    function previewFor(condition) {
        let values = {
            "sunny": ["Sunny", 88, 92, 93, 75, 5, "Warm sunshine", "The sun is smiling! Grab water and sunscreen.", ["sun", "sun", "partly", "moon"]],
            "mostly-clear": ["Mostly clear", 86, 88, 91, 74, 10, "A few cloud friends", "The sun has a few fluffy cloud friends!", ["sun", "partly", "sun", "moon"]],
            "partly": ["Partly cloudy", 87, 89, 91, 76, 30, "Sun-and-cloud team-up", "The sun and clouds are sharing the sky!", ["partly", "partly", "drizzle", "moon"]],
            "cloudy": ["Cloudy", 84, 85, 88, 73, 25, "A soft cloud blanket", "The clouds are having a parade!", ["cloud", "cloud", "partly", "cloud"]],
            "overcast": ["Overcast", 78, 80, 83, 70, 40, "Cloud blanket overhead", "A soft cloud blanket is covering the sky!", ["cloud", "cloud", "cloud", "cloud"]],
            "fog": ["Foggy", 66, 65, 72, 60, 15, "Low visibility", "The clouds came down to visit. Stay where a grown-up can see you!", ["fog", "fog", "cloud", "moon"]],
            "drizzle": ["Drizzly", 67, 66, 71, 61, 55, "Tiny tiptoe raindrops", "A light raincoat could be a cozy sidekick.", ["drizzle", "drizzle", "cloud", "moon"]],
            "rain": ["Rainy", 72, 74, 76, 65, 80, "Puddle weather", "Puddle-jumping weather! Bring your raincoat and boots.", ["rain", "rain", "drizzle", "cloud"]],
            "heavy-rain": ["Heavy rain", 69, 71, 73, 63, 95, "Big raindrops", "Big rain is falling. Raincoat and boots time!", ["rain", "rain", "storm", "rain"]],
            "freezing-rain": ["Freezing rain", 30, 22, 33, 24, 85, "Slippery-ground alert", "Icy rain can make slippery spots. Stay close to a grown-up!", ["sleet", "sleet", "rain", "cloud"]],
            "storm": ["Stormy", 79, 82, 84, 74, 90, "Thunder nearby", "Thunder nearby. Let's stay safely inside with a grown-up!", ["storm", "storm", "rain", "cloud"]],
            "snow": ["Snowy", 28, 20, 31, 19, 85, "Dancing snowflakes", "Bundle up! Coat, hat, gloves, and warm boots.", ["snow", "snow", "snow", "cloud"]],
            "heavy-snow": ["Heavy snow", 21, 11, 25, 12, 95, "Lots of snowflakes", "Lots of snow is dancing down. Bundle up and stay with a grown-up!", ["snow", "snow", "snow", "snow"]],
            "sleet": ["Sleet & ice", 31, 23, 34, 25, 75, "Slippery-ground alert", "Icy drops can make slippery spots. Stay close to a grown-up!", ["sleet", "rain", "sleet", "cloud"]],
            "hail": ["Hail", 62, 58, 66, 52, 80, "Icy pebbles falling", "Hail is falling. Please stay safely inside!", ["storm", "hail", "rain", "cloud"]],
            "wind": ["Very windy", 70, 64, 73, 58, 10, "Hold onto your hat", "Check with a grown-up before a windy adventure!", ["wind", "wind", "partly", "moon"]],
            "hot": ["Very hot", 103, 110, 106, 82, 5, "Heat-safety day", "Water, shade, sunscreen, and plenty of cool-down breaks!", ["sun", "sun", "partly", "moon"]],
            "cold": ["Very cold", 16, 5, 22, 3, 15, "Freezing outside", "Brrr! Coat, hat, gloves, and warm boots.", ["cold", "snow", "cloud", "moon"]],
            "mixed": ["Mixed weather", 63, 61, 68, 54, 45, "A little of everything", "The sky has a little bit of everything today!", ["partly", "rain", "cloud", "moon"]],
            "severe": ["Safety alert", 76, 78, 80, 69, 95, "Official warning active", "BMO safety alert. Go with a grown-up and follow official instructions now.", ["warning", "storm", "rain", "cloud"]]
        }[condition] || ["Today's sky", 72, 72, 76, 64, 20, "Weather adventure", "Let's look at today's sky!", ["cloud", "cloud", "partly", "moon"]]
        let hours = []
        let labels = ["12 PM", "2 PM", "4 PM", "8 PM"]
        for (let index = 0; index < 4; index += 1)
            hours.push({"key": "hour:" + index, "time": labels[index], "temperature": values[1] - index, "icon": values[8][index]})
        return {"name": values[0], "temperature": values[1], "feels": values[2], "high": values[3], "low": values[4], "rain": values[5], "modifier": values[6], "speech": values[7], "hours": hours}
    }

    function displayName() {
        if (!debugActive) return model.condition_name || shownPreview.name
        if (shownTime === "night" && ["sunny", "mostly-clear", "hot"].indexOf(shownCondition) >= 0) return "Clear night"
        return shownPreview.name
    }

    function displayModifier() {
        if (!debugActive) return model.modifier || shownPreview.modifier
        if (shownTime === "night" && ["sunny", "mostly-clear", "partly", "hot"].indexOf(shownCondition) >= 0)
            return shownPhase.replace(/-/g, " ") + " moon"
        return shownPreview.modifier
    }

    function displaySpeech() {
        if (!debugActive) return model.speech || shownPreview.speech
        if (shownTime === "night" && ["sunny", "mostly-clear"].indexOf(shownCondition) >= 0) return "The moon is smiling! Cozy night-sky time."
        if (shownTime === "night" && shownCondition === "partly") return "The moon and clouds are playing peekaboo!"
        if (shownTime === "night" && shownCondition === "hot") return "It is a warm night. Keep water nearby!"
        return shownPreview.speech
    }

    function greeting() {
        if (shownTime === "night") return "Good evening! The night sky is awake."
        if (shownTime === "sunset") return "Sunset is painting the sky!"
        if (shownTime === "afternoon") return "Good afternoon! Here is today's sky."
        if (shownTime === "midday") return "Hello, sunshine! Here is today's sky."
        return "Good morning! Here is today's sky."
    }

    function liveValue(name) {
        if (debugActive || !ready) return shownPreview[name]
        return model[name]
    }

    component InfoCard: Rectangle {
        id: card
        property string label: ""
        property string value: ""
        property bool speaking: false
        signal clicked()
        radius: 15
        color: Qt.rgba(.91, .98, .95, .47)
        border.color: speaking ? "#ffe66f" : "#5d837c"
        border.width: speaking ? 5 : 4
        Column {
            anchors.centerIn: parent
            spacing: 2
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: card.label; color: "#477269"; font.pixelSize: 15; font.bold: true }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: card.value; color: "#123e38"; font.pixelSize: 29; font.bold: true }
        }
        MouseArea { anchors.fill: parent; enabled: root.ready && !root.debugActive && root.model.speech_available === true; onClicked: card.clicked() }
    }

    Rectangle { anchors.fill: parent; color: "#101514" }

    Item {
        width: 800
        height: 480
        anchors.centerIn: parent
        scale: root.uiScale

        Rectangle {
            x: 5; y: 4; width: 790; height: 469; radius: 35
            color: "#75cbb5"
            border.color: "#153f39"; border.width: 9
        }
        Rectangle {
            x: 14; y: 13; width: 772; height: 451; radius: 29
            color: "transparent"
            border.color: "#a2ead9"; border.width: 3
        }
        Rectangle {
            id: screen
            x: 22; y: 20; width: 756; height: 437; radius: 23
            color: "#dff7ef"
            border.color: "#153f39"; border.width: 7
            clip: true

            Rectangle {
                id: header
                x: 7; y: 7; width: 742; height: 63
                color: "#e3f8f1"
                Text {
                    x: 18; y: 5; width: 560; height: 37
                    text: root.model.location || "Weather"
                    color: "#123e38"; font.pixelSize: 34; font.bold: true
                    elide: Text.ElideRight
                }
                Text {
                    x: 19; y: 41; width: 560; height: 18
                    text: root.greeting()
                    color: "#3c6d64"; font.pixelSize: 14; font.bold: true
                    elide: Text.ElideRight
                }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom; anchors.bottomMargin: 4
                    spacing: 6
                    Repeater {
                        model: Math.min(8, Number(root.model.page_count || 0))
                        delegate: Rectangle {
                            required property int index
                            width: 7; height: 7; radius: 4
                            color: index === Number(root.model.page_index || 0) ? "#2f665c" : "#a7cec3"
                        }
                    }
                }
                Text {
                    visible: Number(root.model.page_count || 0) > 1
                    x: 618; y: 21; text: "‹"; color: "#477269"; font.pixelSize: 24; font.bold: true
                    MouseArea { anchors.fill: parent; anchors.margins: -9; onClicked: root.send("weather_previous") }
                }
                Text {
                    visible: Number(root.model.page_count || 0) > 1
                    x: 728; y: 21; text: "›"; color: "#477269"; font.pixelSize: 24; font.bold: true
                    MouseArea { anchors.fill: parent; anchors.margins: -9; onClicked: root.send("weather_next") }
                }
                Image {
                    id: bmoFace
                    x: 635; y: 6; width: 91; height: 52
                    source: root.controller.frameSource
                    fillMode: Image.PreserveAspectFit
                    cache: false
                    asynchronous: false
                    Rectangle { anchors.fill: parent; color: "#68c8bb"; border.color: "#153f39"; border.width: 3; radius: 8; z: -1 }
                    MouseArea { anchors.fill: parent; onClicked: root.controller.requestViewClose() }
                }
            }

            Rectangle { x: 7; y: 69; width: 742; height: 2; color: "#9bc9bf" }

            WeatherScene {
                id: scene
                x: 7; y: 71; width: 742; height: 291
                condition: root.shownCondition
                timeOfDay: root.shownTime
                season: root.shownSeason
                phase: root.shownPhase
                animations: root.model.animations !== false
            }

            Rectangle {
                visible: root.shownCondition === "severe"
                         || (root.ready && !root.debugActive && Boolean(root.model.alert))
                x: 22; y: 79; width: 698; height: 35; radius: 9
                color: "#bd3848"; border.color: "#681e28"; border.width: 3
                Text { anchors.centerIn: parent; width: parent.width - 20; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; text: "BMO SAFETY ALERT — " + (root.model.alert || "GO WITH A GROWN-UP AND FOLLOW OFFICIAL INSTRUCTIONS"); color: "white"; font.pixelSize: 14; font.bold: true }
                MouseArea { anchors.fill: parent; onClicked: root.speak("alert") }
            }

            Item {
                id: readout
                x: 383; y: root.shownCondition === "severe" ? 112 : 84; width: 340; height: 201
                Text {
                    x: 0; y: 0; width: parent.width; height: 75
                    text: String(root.liveValue("temperature")) + "°"
                    color: root.readoutColor; font.pixelSize: root.shownCondition === "severe" ? 65 : 76; font.bold: true
                    horizontalAlignment: Text.AlignRight; verticalAlignment: Text.AlignVCenter
                    MouseArea { anchors.fill: parent; onClicked: root.speak("temperature") }
                }
                Text {
                    x: 0; y: 73; width: parent.width; height: 37
                    text: root.displayName(); color: root.readoutColor
                    font.pixelSize: 31; font.bold: true; horizontalAlignment: Text.AlignRight
                    elide: Text.ElideRight
                }
                Text {
                    x: 0; y: 108; width: parent.width; height: 20
                    text: root.displayModifier().toUpperCase()
                    color: root.darkText ? "#985134" : "#ffe89c"
                    font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignRight
                    elide: Text.ElideRight
                }
                Rectangle {
                    x: 20; y: 130; width: 320; height: 66; radius: 15
                    color: "#fff5ba"; border.color: (root.model.speaking_key || "") === "condition" ? "#ffe66f" : "#153f39"; border.width: (root.model.speaking_key || "") === "condition" ? 5 : 4
                    Text { anchors.fill: parent; anchors.margins: 14; text: root.displaySpeech(); color: "#153f39"; font.pixelSize: 15; font.bold: true; wrapMode: Text.Wrap; verticalAlignment: Text.AlignVCenter }
                    MouseArea { anchors.fill: parent; onClicked: root.speak("condition") }
                }
            }

            Row {
                x: 24; y: 276; width: 700; height: 72; spacing: 14
                InfoCard { width: 224; height: parent.height; label: "Feels like"; value: String(root.liveValue("feels")) + "°"; speaking: (root.model.speaking_key || "") === "feels"; onClicked: root.speak("feels") }
                InfoCard { width: 224; height: parent.height; label: "High · Low"; value: String(root.liveValue("high")) + "° · " + String(root.liveValue("low")) + "°"; speaking: (root.model.speaking_key || "") === "high_low"; onClicked: root.speak("high_low") }
                InfoCard { width: 224; height: parent.height; label: "Rain today"; value: String(root.liveValue("rain")) + "%"; speaking: (root.model.speaking_key || "") === "rain"; onClicked: root.speak("rain") }
            }

            Rectangle {
                x: 7; y: 361; width: 742; height: 69
                color: "#e0f7ee"
                border.color: "#9bc9bf"; border.width: 2
                Text { x: 20; y: 0; width: 158; height: parent.height; verticalAlignment: Text.AlignVCenter; text: "Later today"; color: "#123e38"; font.pixelSize: 27; font.bold: true }
                Row {
                    x: 172; y: 2; width: 562; height: 65; spacing: 2
                    Repeater {
                        model: root.shownHours
                        delegate: Item {
                            required property var modelData
                            width: 138; height: 65
                            WeatherIcon { x: 0; y: 5; width: 65; height: 56; icon: modelData.icon || "cloud"; phase: root.shownPhase }
                            Text { x: 62; y: 8; width: 76; height: 24; text: modelData.time || ""; color: "#477269"; font.pixelSize: 16; font.bold: true }
                            Text { x: 62; y: 31; width: 76; height: 30; text: String(modelData.temperature) + "°"; color: "#123e38"; font.pixelSize: 24; font.bold: true }
                            Rectangle { anchors.fill: parent; color: "transparent"; border.color: (root.model.speaking_key || "") === (modelData.key || "") ? "#ffe66f" : "transparent"; border.width: 4; radius: 10 }
                            MouseArea { anchors.fill: parent; onClicked: root.speak(modelData.key || "") }
                        }
                    }
                }
            }

            Rectangle {
                visible: !root.ready && !root.debugActive
                x: 7; y: 71; width: 742; height: 291
                color: scene.skyColor()
                Text { anchors.centerIn: parent; width: parent.width - 100; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; text: root.model.message || "BMO is checking the sky..."; color: "#123e38"; font.pixelSize: 24; font.bold: true }
                MouseArea { anchors.fill: parent; onClicked: root.send("weather_retry") }
            }

            DragHandler {
                id: swipeHandler
                target: null
                acceptedButtons: Qt.LeftButton
                onActiveChanged: {
                    if (active) {
                        root.swipeDx = 0
                        root.swipeDy = 0
                    } else if (Math.abs(root.swipeDx) >= 55
                               && Math.abs(root.swipeDx) > Math.abs(root.swipeDy) * 1.25) {
                        root.send(root.swipeDx < 0 ? "weather_next" : "weather_previous")
                    }
                }
                onActiveTranslationChanged: {
                    if (active) {
                        root.swipeDx = activeTranslation.x
                        root.swipeDy = activeTranslation.y
                    }
                }
            }
        }

        Rectangle {
            visible: root.model.debug === true && !root.debugOpen
            x: 386; y: 4; width: 28; height: 28; radius: 14
            color: "#153f39"; z: 300
            Text { anchors.centerIn: parent; text: "D"; color: "white"; font.pixelSize: 12; font.bold: true }
            MouseArea { anchors.fill: parent; onClicked: root.debugOpen = true }
        }

        Rectangle {
            visible: root.model.debug === true && root.debugOpen
            x: 18; y: 10; width: 764; height: 455; radius: 18
            color: "#f1fff9"; border.color: "#2e665c"; border.width: 3; z: 400
            Flickable {
                anchors.fill: parent; anchors.margins: 12
                contentWidth: width; contentHeight: debugContent.height
                clip: true
                Column {
                    id: debugContent
                    width: parent.width; spacing: 6
                    Row {
                        width: parent.width; height: 34
                        Text { width: parent.width - 220; height: 34; verticalAlignment: Text.AlignVCenter; text: "Weather graphics debugger"; color: "#123e38"; font.pixelSize: 18; font.bold: true }
                        Button { width: 105; height: 34; text: "LIVE"; onClicked: { root.debugActive = false; root.debugOpen = false } }
                        Button { width: 105; height: 34; text: "CLOSE"; onClicked: root.debugOpen = false }
                    }
                    Text { text: "WEATHER CONDITION"; color: "#477269"; font.pixelSize: 12; font.bold: true }
                    Flow {
                        width: parent.width; height: 100; spacing: 5
                        Repeater {
                            model: root.conditions
                            delegate: Button {
                                required property var modelData
                                width: Math.max(78, Math.min(126, implicitWidth + 15)); height: 29
                                text: modelData[1]; checkable: true; checked: root.debugActive && root.debugCondition === modelData[0]
                                onClicked: { root.debugActive = true; root.debugCondition = modelData[0] }
                            }
                        }
                    }
                    Text { text: "SEASON"; color: "#477269"; font.pixelSize: 12; font.bold: true }
                    Flow {
                        width: parent.width; height: 34; spacing: 5
                        Repeater { model: root.seasons; delegate: Button { required property var modelData; height: 29; text: modelData[1]; checkable: true; checked: root.debugActive && root.debugSeason === modelData[0]; onClicked: { root.debugActive = true; root.debugSeason = modelData[0] } } }
                    }
                    Text { text: "TIME OF DAY"; color: "#477269"; font.pixelSize: 12; font.bold: true }
                    Flow {
                        width: parent.width; height: 34; spacing: 5
                        Repeater { model: root.times; delegate: Button { required property var modelData; height: 29; text: modelData[1]; checkable: true; checked: root.debugActive && root.debugTime === modelData[0]; onClicked: { root.debugActive = true; root.debugTime = modelData[0] } } }
                    }
                    Text { text: "MOON PHASE"; color: "#477269"; font.pixelSize: 12; font.bold: true }
                    Flow {
                        width: parent.width; height: 68; spacing: 5
                        Repeater { model: root.phases; delegate: Button { required property var modelData; height: 29; text: modelData[1]; checkable: true; checked: root.debugActive && root.debugPhase === modelData[0]; onClicked: { root.debugActive = true; root.debugPhase = modelData[0] } } }
                    }
                }
            }
        }
    }
}
