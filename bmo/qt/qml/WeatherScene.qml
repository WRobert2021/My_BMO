import QtQuick

Item {
    id: root
    clip: true
    property string condition: "sunny"
    property string timeOfDay: "morning"
    property string season: "summer"
    property string phase: "full"
    property bool animations: true
    readonly property bool storm: condition === "storm" || condition === "severe"
    property real stormClock: 0

    NumberAnimation on stormClock {
        from: 0; to: 1; duration: 4600
        loops: Animation.Infinite
        running: root.animations && root.storm
    }

    function lightningPulse(start, finish) {
        return stormClock >= start && stormClock <= finish
    }

    function skyColor() {
        if (condition === "storm" || condition === "severe") return "#6f83aa"
        if (timeOfDay === "night") return "#526b91"
        if (timeOfDay === "sunset") return "#f0aa8c"
        if (timeOfDay === "afternoon") return "#86c8df"
        if (timeOfDay === "midday") return "#80d4ef"
        return "#9ddff3"
    }

    function sceneIcon() {
        if (condition === "sunny" || condition === "hot") return timeOfDay === "night" ? "moon" : "sun"
        if (condition === "mostly-clear" || condition === "partly" || condition === "mixed") return timeOfDay === "night" ? "moon-cloud" : "partly"
        if (condition === "cloudy" || condition === "overcast") return "cloud"
        if (condition === "fog") return "fog"
        if (condition === "drizzle") return "drizzle"
        if (condition === "rain" || condition === "heavy-rain") return "rain"
        if (condition === "freezing-rain" || condition === "sleet") return "sleet"
        if (condition === "snow" || condition === "heavy-snow") return "snow"
        if (condition === "hail") return "hail"
        if (condition === "storm" || condition === "severe") return "cloud"
        if (condition === "wind") return "wind"
        if (condition === "cold") return "cold"
        return "cloud"
    }

    function precipType() {
        if (["drizzle", "rain", "heavy-rain", "storm", "severe", "mixed"].indexOf(condition) >= 0) return "rain"
        if (["snow", "heavy-snow"].indexOf(condition) >= 0) return "snow"
        if (["freezing-rain", "sleet"].indexOf(condition) >= 0) return "sleet"
        if (condition === "hail") return "hail"
        if (condition === "wind") return "wind"
        return ""
    }

    function precipCount() {
        if (condition === "heavy-rain" || condition === "heavy-snow") return 28
        if (condition === "drizzle") return 10
        if (precipType() === "wind") return 7
        return precipType() === "" ? 0 : 18
    }

    Rectangle {
        anchors.fill: parent
        color: root.skyColor()
        Behavior on color { ColorAnimation { duration: root.animations ? 350 : 0 } }
    }

    Repeater {
        model: root.timeOfDay === "night" ? 8 : 0
        delegate: Rectangle {
            required property int index
            x: 35 + ((index * 107) % Math.max(1, root.width - 70))
            y: 18 + ((index * 41) % 105)
            width: 4 + (index % 2) * 2
            height: width
            radius: width / 2
            color: "#fff6b0"
            opacity: .45
            SequentialAnimation on opacity {
                loops: Animation.Infinite
                running: root.animations
                NumberAnimation { to: 1; duration: 700 + index * 90 }
                NumberAnimation { to: .35; duration: 750 + index * 60 }
            }
        }
    }

    Canvas {
        id: ground
        anchors.fill: parent
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            let ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            let bottom = height + 25
            let hillOne = root.season === "fall" ? "#bc8e54" : root.season === "winter" ? "#b8c7c3" : "#87c878"
            let hillTwo = root.season === "fall" ? "#9d7548" : root.season === "winter" ? "#94aaa5" : "#6db66f"
            ctx.globalAlpha = root.season === "winter" ? .62 : .82
            ctx.fillStyle = hillOne
            ctx.beginPath(); ctx.ellipse(width * .22, bottom, width * .38, height * .28, 0, Math.PI, Math.PI * 2); ctx.fill()
            ctx.fillStyle = hillTwo
            ctx.beginPath(); ctx.ellipse(width * .72, bottom + 4, width * .46, height * .29, 0, Math.PI, Math.PI * 2); ctx.fill()
            ctx.globalAlpha = 1

            // Tall foreground grass remains readable through the translucent
            // forecast cards and gives every seasonal ground layer texture.
            let grassColor = root.season === "fall" ? "#9a7139" : root.season === "winter" ? "#d9e9e4" : "#398e52"
            ctx.strokeStyle = grassColor
            ctx.lineWidth = 2.2
            ctx.lineCap = "round"
            for (let tuft = 0; tuft < 28; tuft += 1) {
                let gx = 13 + ((tuft * 61) % Math.max(1, width - 22))
                let gy = height - 3 - (tuft % 3) * 2
                let blade = 19 + (tuft % 5) * 5
                ctx.beginPath()
                ctx.moveTo(gx, gy); ctx.quadraticCurveTo(gx - 4, gy - blade * .62, gx - 9, gy - blade)
                ctx.moveTo(gx, gy); ctx.quadraticCurveTo(gx + 1, gy - blade * .72, gx + 2, gy - blade * 1.12)
                ctx.moveTo(gx, gy); ctx.quadraticCurveTo(gx + 6, gy - blade * .6, gx + 10, gy - blade * .88)
                ctx.stroke()
            }

            if (root.season === "summer" || root.season === "fall") {
                ctx.fillStyle = "#765542"; ctx.fillRect(width * .065, height * .68, 16, height * .26)
                ctx.fillStyle = root.season === "fall" ? "#d26e36" : "#63ae66"
                ctx.beginPath(); ctx.arc(width * .075, height * .67, 43, 0, Math.PI * 2); ctx.fill()
                ctx.beginPath(); ctx.arc(width * .04, height * .72, 31, 0, Math.PI * 2); ctx.fill()
                ctx.beginPath(); ctx.arc(width * .11, height * .72, 32, 0, Math.PI * 2); ctx.fill()
            }

            if (root.season === "spring" || root.season === "summer") {
                let flowerColors = ["#f47ea8", "#9a75d7", "#f4b741", "#ffffff"]
                for (let index = 0; index < 10; index += 1) {
                    let x = 38 + ((index * 79) % (width - 70))
                    let y = height - 29 - (index % 3) * 5
                    ctx.strokeStyle = "#4f9a55"; ctx.lineWidth = 2
                    ctx.beginPath(); ctx.moveTo(x, y + 5); ctx.lineTo(x, y + 19); ctx.stroke()
                    ctx.fillStyle = flowerColors[index % flowerColors.length]
                    for (let petal = 0; petal < 5; petal += 1) {
                        let a = petal * Math.PI * 2 / 5
                        ctx.beginPath(); ctx.arc(x + Math.cos(a) * 5, y + Math.sin(a) * 5, 4, 0, Math.PI * 2); ctx.fill()
                    }
                    ctx.fillStyle = "#ffd45e"; ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill()
                }
            } else if (root.season === "fall") {
                for (let pile = 0; pile < 2; pile += 1) {
                    let x = pile === 0 ? width * .22 : width * .75
                    let y = height - 16
                    let colors = ["#cf642f", "#e69e2e", "#af482b", "#d9782f"]
                    for (let leaf = 0; leaf < 9; leaf += 1) {
                        ctx.fillStyle = colors[leaf % colors.length]
                        ctx.beginPath(); ctx.ellipse(x + (leaf - 4) * 8, y - (leaf % 3) * 7, 13, 7, (leaf % 4) * .4, 0, Math.PI * 2); ctx.fill()
                    }
                }
            } else if (root.season === "winter") {
                ctx.strokeStyle = "#745b4d"; ctx.lineWidth = 7; ctx.lineCap = "round"
                ctx.beginPath(); ctx.moveTo(42, height - 8); ctx.quadraticCurveTo(47, height - 82, 70, height - 112); ctx.moveTo(58, height - 64); ctx.lineTo(31, height - 91); ctx.moveTo(64, height - 81); ctx.lineTo(91, height - 104); ctx.stroke()
                for (let pine = 0; pine < 2; pine += 1) {
                    let x = pine === 0 ? width * .22 : width * .84
                    ctx.fillStyle = "#4d7f68"
                    ctx.beginPath(); ctx.moveTo(x, height - 105); ctx.lineTo(x - 40, height - 16); ctx.lineTo(x + 40, height - 16); ctx.closePath(); ctx.fill()
                    ctx.fillStyle = "#745b4d"; ctx.fillRect(x - 4, height - 21, 8, 18)
                }
            }
        }
        Connections {
            target: root
            function onSeasonChanged() { ground.requestPaint() }
        }
    }

    Repeater {
        model: (root.season === "spring" || root.season === "fall") ? 18 : 0
        delegate: Rectangle {
            required property int index
            property bool petal: root.season === "spring"
            x: (index * 73 + 17) % Math.max(1, root.width - 20)
            y: -12
            width: petal ? 8 : 11
            height: petal ? 6 : 8
            radius: petal ? 5 : 2
            color: petal
                   ? (index % 2 ? "#ffd1df" : "#f584a7")
                   : (["#d65c2d", "#e6a22e", "#b64c2e"])[index % 3]
            rotation: index * 27
            opacity: .86
            NumberAnimation on y {
                from: -15 - index * 7
                to: root.height + 20
                duration: 4300 + (index % 5) * 520
                loops: Animation.Infinite
                running: root.animations
            }
            RotationAnimation on rotation {
                from: index * 27
                to: index * 27 + 310
                duration: 3200 + index * 110
                loops: Animation.Infinite
                running: root.animations
            }
        }
    }

    WeatherIcon {
        id: mainArt
        x: 20
        y: 7
        width: 330
        height: 220
        icon: root.sceneIcon()
        phase: root.phase
        SequentialAnimation on y {
            loops: Animation.Infinite
            running: root.animations
            NumberAnimation { from: 7; to: 0; duration: 1300; easing.type: Easing.InOutSine }
            NumberAnimation { from: 0; to: 7; duration: 1300; easing.type: Easing.InOutSine }
        }
    }

    Repeater {
        model: root.precipCount()
        delegate: Rectangle {
            required property int index
            property string kind: root.precipType()
            property bool sleetDrop: kind === "sleet" && index % 2 === 0
            x: kind === "wind" ? -145 : ((index * 127 + 31) % Math.max(1, root.width - 18))
            y: kind === "wind" ? 22 + ((index * 43) % Math.max(1, root.height - 70)) : -35
            width: kind === "wind" ? 132 : (kind === "rain" || sleetDrop) ? 5 : kind === "hail" ? 8 + index % 3 : 10
            height: kind === "wind" ? 6 : (kind === "rain" || sleetDrop) ? 25 : kind === "hail" ? 7 + (index + 1) % 3 : 10
            radius: kind === "wind" || kind === "rain" || sleetDrop || kind === "snow" ? width / 2 : 2
            color: kind === "rain" ? "#258dcc" : sleetDrop ? "#3e9ed1" : kind === "snow" ? "#ffffff" : kind === "wind" ? "#ecfdff" : kind === "hail" ? (index % 2 ? "#d9f6ff" : "#b9e6f2") : "#c8eff9"
            border.color: kind === "hail" || (kind === "sleet" && !sleetDrop) ? "#5f91a5" : "transparent"
            border.width: kind === "hail" || (kind === "sleet" && !sleetDrop) ? 2 : 0
            opacity: kind === "wind" ? .6 : .76
            rotation: kind === "rain" || sleetDrop ? 18 : kind === "sleet" ? 45 : index * 19
            NumberAnimation on y {
                from: -40 - (index % 6) * 24
                to: root.height + 30
                duration: kind === "snow" ? 3200 + (index % 4) * 650 : kind === "hail" ? 850 + (index % 4) * 110 : kind === "sleet" ? 1050 + (index % 3) * 120 : 1150 + (index % 4) * 90
                loops: Animation.Infinite
                running: root.animations && kind !== "wind"
            }
            NumberAnimation on x {
                from: -150 - index * 31
                to: root.width + 160
                duration: 1800 + (index % 3) * 240
                loops: Animation.Infinite
                running: root.animations && kind === "wind"
            }
            RotationAnimation on rotation {
                from: index * 15
                to: index * 15 + 250
                duration: 2700
                loops: Animation.Infinite
                running: root.animations && (kind === "snow" || kind === "hail" || (kind === "sleet" && !sleetDrop))
            }
            SequentialAnimation on scale {
                loops: Animation.Infinite
                running: root.animations && kind === "hail"
                NumberAnimation { from: 1; to: .76; duration: 310 + index * 7; easing.type: Easing.InOutSine }
                NumberAnimation { from: .76; to: 1; duration: 310 + index * 7; easing.type: Easing.InOutSine }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "white"
        z: 1
        opacity: root.storm && root.animations
                 && (root.lightningPulse(.20, .225) || root.lightningPulse(.245, .268)) ? .2 : 0
        visible: root.storm
    }

    WeatherBolt {
        x: 145; y: 137; width: 62; height: 82; z: 3
        visible: root.storm
        opacity: !root.animations || root.lightningPulse(.20, .225) || root.lightningPulse(.245, .268) ? 1 : 0
    }
    WeatherBolt {
        x: 53; y: 128; width: 42; height: 58; z: 3
        visible: root.storm
        opacity: !root.animations ? .78 : root.lightningPulse(.49, .525) ? .9 : 0
        fillColor: "#fff08a"
    }
    WeatherBolt {
        x: 276; y: 119; width: 48; height: 67; z: 3
        visible: root.storm
        opacity: !root.animations ? .7 : root.lightningPulse(.73, .765) ? .88 : 0
        fillColor: "#fff08a"
    }
}
