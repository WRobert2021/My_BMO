import QtQuick

Canvas {
    id: root
    property string icon: "cloud"
    property string phase: "full"

    onIconChanged: requestPaint()
    onPhaseChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    Component.onCompleted: requestPaint()

    function pathCloud(ctx, x, y, scale) {
        ctx.beginPath()
        ctx.moveTo(x + 8 * scale, y + 39 * scale)
        ctx.bezierCurveTo(x - 3 * scale, y + 39 * scale,
                          x - 4 * scale, y + 23 * scale,
                          x + 7 * scale, y + 20 * scale)
        ctx.bezierCurveTo(x + 9 * scale, y + 6 * scale,
                          x + 25 * scale, y + 1 * scale,
                          x + 35 * scale, y + 11 * scale)
        ctx.bezierCurveTo(x + 46 * scale, y + 1 * scale,
                          x + 63 * scale, y + 8 * scale,
                          x + 62 * scale, y + 23 * scale)
        ctx.bezierCurveTo(x + 75 * scale, y + 24 * scale,
                          x + 77 * scale, y + 39 * scale,
                          x + 65 * scale, y + 39 * scale)
        ctx.closePath()
    }

    function drawCloud(ctx, x, y, scale) {
        pathCloud(ctx, x + 1.5 * scale, y + 4 * scale, scale)
        ctx.fillStyle = "#88bcc9"
        ctx.fill()
        pathCloud(ctx, x, y, scale)
        ctx.fillStyle = "#eef8fb"
        ctx.strokeStyle = "#547784"
        ctx.lineWidth = 3 * scale
        ctx.lineJoin = "round"
        ctx.fill()
        ctx.stroke()
        ctx.fillStyle = "#315660"
        ctx.beginPath(); ctx.arc(x + 31 * scale, y + 28 * scale, 1.7 * scale, 0, Math.PI * 2); ctx.fill()
        ctx.beginPath(); ctx.arc(x + 41 * scale, y + 28 * scale, 1.7 * scale, 0, Math.PI * 2); ctx.fill()
        ctx.beginPath()
        ctx.moveTo(x + 31 * scale, y + 33 * scale)
        ctx.quadraticCurveTo(x + 36 * scale, y + 37 * scale, x + 41 * scale, y + 33 * scale)
        ctx.strokeStyle = "#315660"; ctx.lineWidth = 2 * scale; ctx.stroke()
    }

    function drawSun(ctx, x, y, radius) {
        ctx.strokeStyle = "#e49a20"
        ctx.lineWidth = Math.max(2, radius * .12)
        ctx.lineCap = "round"
        for (let index = 0; index < 8; index += 1) {
            let angle = index * Math.PI / 4
            ctx.beginPath()
            ctx.moveTo(x + Math.cos(angle) * radius * 1.35, y + Math.sin(angle) * radius * 1.35)
            ctx.lineTo(x + Math.cos(angle) * radius * 1.7, y + Math.sin(angle) * radius * 1.7)
            ctx.stroke()
        }
        ctx.fillStyle = "#ffdc5a"; ctx.strokeStyle = "#d88612"; ctx.lineWidth = Math.max(2, radius * .11)
        ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill(); ctx.stroke()
        ctx.fillStyle = "#6c4a24"
        ctx.beginPath(); ctx.arc(x - radius * .3, y - radius * .12, radius * .08, 0, Math.PI * 2); ctx.fill()
        ctx.beginPath(); ctx.arc(x + radius * .3, y - radius * .12, radius * .08, 0, Math.PI * 2); ctx.fill()
        ctx.beginPath(); ctx.moveTo(x - radius * .28, y + radius * .24); ctx.quadraticCurveTo(x, y + radius * .47, x + radius * .3, y + radius * .23)
        ctx.strokeStyle = "#6c4a24"; ctx.lineWidth = Math.max(2, radius * .09); ctx.stroke()
    }

    function drawSnowflake(ctx, x, y, radius) {
        ctx.save()
        ctx.translate(x, y)
        ctx.strokeStyle = "#68a9c8"
        ctx.lineWidth = Math.max(1.4, radius * .24)
        ctx.lineCap = "round"
        for (let arm = 0; arm < 3; arm += 1) {
            let angle = arm * Math.PI / 3
            ctx.save()
            ctx.rotate(angle)
            ctx.beginPath()
            ctx.moveTo(-radius, 0)
            ctx.lineTo(radius, 0)
            ctx.moveTo(radius * .48, 0)
            ctx.lineTo(radius * .75, -radius * .28)
            ctx.moveTo(radius * .48, 0)
            ctx.lineTo(radius * .75, radius * .28)
            ctx.moveTo(-radius * .48, 0)
            ctx.lineTo(-radius * .75, -radius * .28)
            ctx.moveTo(-radius * .48, 0)
            ctx.lineTo(-radius * .75, radius * .28)
            ctx.stroke()
            ctx.restore()
        }
        ctx.restore()
    }

    function moonShadow(ctx, x, y, radius) {
        let shadow = "#526b85"
        ctx.fillStyle = shadow
        ctx.save()
        ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.clip()
        if (phase === "new") {
            ctx.beginPath(); ctx.arc(x, y, radius + 1, 0, Math.PI * 2); ctx.fill()
        } else if (phase === "waxing-crescent") {
            ctx.beginPath(); ctx.moveTo(x, y - radius)
            ctx.arc(x, y, radius, -Math.PI / 2, Math.PI / 2, true)
            ctx.quadraticCurveTo(x + radius * 1.05, y, x, y - radius)
            ctx.closePath(); ctx.fill()
        } else if (phase === "waning-crescent") {
            ctx.beginPath(); ctx.moveTo(x, y - radius)
            ctx.arc(x, y, radius, -Math.PI / 2, Math.PI / 2, false)
            ctx.quadraticCurveTo(x - radius * 1.05, y, x, y - radius)
            ctx.closePath(); ctx.fill()
        } else if (phase === "first-quarter") {
            ctx.fillRect(x - radius, y - radius, radius, radius * 2)
        } else if (phase === "last-quarter") {
            ctx.fillRect(x, y - radius, radius, radius * 2)
        } else if (phase === "waxing-gibbous") {
            ctx.beginPath(); ctx.moveTo(x, y - radius)
            ctx.arc(x, y, radius, -Math.PI / 2, Math.PI / 2, true)
            ctx.quadraticCurveTo(x - radius * .75, y, x, y - radius)
            ctx.closePath(); ctx.fill()
        } else if (phase === "waning-gibbous") {
            ctx.beginPath(); ctx.moveTo(x, y - radius)
            ctx.arc(x, y, radius, -Math.PI / 2, Math.PI / 2, false)
            ctx.quadraticCurveTo(x + radius * .75, y, x, y - radius)
            ctx.closePath(); ctx.fill()
        }
        ctx.restore()
    }

    function drawMoon(ctx, x, y, radius) {
        ctx.fillStyle = "#fff3a6"
        ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill()
        moonShadow(ctx, x, y, radius)

        // Only the illuminated outer limb is gold. The dark edge deliberately
        // has no yellow ring, so quarter and gibbous phases read correctly.
        ctx.strokeStyle = "#d0a92d"
        ctx.lineWidth = Math.max(2, radius * .1)
        ctx.lineCap = "round"
        if (phase === "full") {
            ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.stroke()
        } else if (["waxing-crescent", "first-quarter", "waxing-gibbous"].indexOf(phase) >= 0) {
            ctx.beginPath(); ctx.arc(x, y, radius, -Math.PI / 2, Math.PI / 2); ctx.stroke()
        } else if (["waning-crescent", "last-quarter", "waning-gibbous"].indexOf(phase) >= 0) {
            ctx.beginPath(); ctx.arc(x, y, radius, Math.PI / 2, Math.PI * 1.5); ctx.stroke()
        }

        let face = "#5b4b38"
        ctx.fillStyle = face
        ctx.strokeStyle = face
        ctx.lineWidth = Math.max(2, radius * .08)
        if (phase === "full") {
            ctx.beginPath(); ctx.arc(x - radius * .28, y - radius * .07, radius * .08, 0, Math.PI * 2); ctx.fill()
            ctx.beginPath(); ctx.arc(x + radius * .28, y - radius * .07, radius * .08, 0, Math.PI * 2); ctx.fill()
            ctx.beginPath(); ctx.moveTo(x - radius * .26, y + radius * .27); ctx.quadraticCurveTo(x, y + radius * .46, x + radius * .29, y + radius * .25); ctx.stroke()
        } else if (["first-quarter", "waxing-gibbous"].indexOf(phase) >= 0) {
            ctx.beginPath(); ctx.arc(x + radius * .31, y - radius * .08, radius * .08, 0, Math.PI * 2); ctx.fill()
            ctx.beginPath(); ctx.moveTo(x + radius * .05, y + radius * .26); ctx.quadraticCurveTo(x + radius * .25, y + radius * .42, x + radius * .43, y + radius * .22); ctx.stroke()
        } else if (["last-quarter", "waning-gibbous"].indexOf(phase) >= 0) {
            ctx.beginPath(); ctx.arc(x - radius * .31, y - radius * .08, radius * .08, 0, Math.PI * 2); ctx.fill()
            ctx.beginPath(); ctx.moveTo(x - radius * .05, y + radius * .26); ctx.quadraticCurveTo(x - radius * .25, y + radius * .42, x - radius * .43, y + radius * .22); ctx.stroke()
        }
    }

    function drawIceCube(ctx, scale) {
        ctx.lineJoin = "round"
        ctx.lineWidth = 3 * scale
        ctx.strokeStyle = "#4f7d91"

        ctx.fillStyle = "#d8f6ff"
        ctx.beginPath()
        ctx.moveTo(18 * scale, 16 * scale)
        ctx.lineTo(27 * scale, 7 * scale)
        ctx.lineTo(62 * scale, 7 * scale)
        ctx.lineTo(55 * scale, 16 * scale)
        ctx.closePath(); ctx.fill(); ctx.stroke()

        ctx.fillStyle = "#a9deef"
        ctx.beginPath()
        ctx.moveTo(55 * scale, 16 * scale)
        ctx.lineTo(62 * scale, 7 * scale)
        ctx.lineTo(62 * scale, 44 * scale)
        ctx.lineTo(55 * scale, 53 * scale)
        ctx.closePath(); ctx.fill(); ctx.stroke()

        ctx.fillStyle = "#c8eff9"
        ctx.beginPath()
        ctx.moveTo(18 * scale, 16 * scale)
        ctx.lineTo(55 * scale, 16 * scale)
        ctx.lineTo(55 * scale, 53 * scale)
        ctx.lineTo(18 * scale, 53 * scale)
        ctx.closePath(); ctx.fill(); ctx.stroke()

        ctx.fillStyle = "#315660"
        ctx.beginPath(); ctx.arc(29 * scale, 32 * scale, 2 * scale, 0, Math.PI * 2); ctx.fill()
        ctx.beginPath(); ctx.arc(43 * scale, 32 * scale, 2 * scale, 0, Math.PI * 2); ctx.fill()
        ctx.beginPath(); ctx.moveTo(29 * scale, 40 * scale); ctx.quadraticCurveTo(36 * scale, 46 * scale, 44 * scale, 39 * scale)
        ctx.strokeStyle = "#315660"; ctx.lineWidth = 2.2 * scale; ctx.stroke()

        ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2 * scale; ctx.lineCap = "round"
        ctx.beginPath(); ctx.moveTo(23 * scale, 21 * scale); ctx.lineTo(23 * scale, 27 * scale); ctx.moveTo(20 * scale, 24 * scale); ctx.lineTo(26 * scale, 24 * scale); ctx.stroke()
    }

    function drawWindLeaf(ctx, scale) {
        ctx.strokeStyle = "#e8fbff"; ctx.lineWidth = 2.5 * scale; ctx.lineCap = "round"
        ctx.beginPath(); ctx.moveTo(8 * scale, 18 * scale); ctx.quadraticCurveTo(21 * scale, 10 * scale, 34 * scale, 18 * scale); ctx.quadraticCurveTo(44 * scale, 25 * scale, 54 * scale, 18 * scale); ctx.stroke()
        ctx.beginPath(); ctx.moveTo(15 * scale, 47 * scale); ctx.quadraticCurveTo(27 * scale, 54 * scale, 39 * scale, 47 * scale); ctx.stroke()

        ctx.fillStyle = "#e98a3e"; ctx.strokeStyle = "#9b5931"; ctx.lineWidth = 2.5 * scale
        ctx.beginPath()
        ctx.moveTo(20 * scale, 31 * scale)
        ctx.bezierCurveTo(30 * scale, 17 * scale, 54 * scale, 19 * scale, 60 * scale, 33 * scale)
        ctx.bezierCurveTo(48 * scale, 46 * scale, 29 * scale, 47 * scale, 20 * scale, 31 * scale)
        ctx.closePath(); ctx.fill(); ctx.stroke()
        ctx.beginPath(); ctx.moveTo(19 * scale, 31 * scale); ctx.lineTo(10 * scale, 25 * scale); ctx.stroke()
        ctx.fillStyle = "#68452f"
        ctx.beginPath(); ctx.arc(37 * scale, 30 * scale, 1.4 * scale, 0, Math.PI * 2); ctx.fill()
        ctx.beginPath(); ctx.arc(45 * scale, 30 * scale, 1.4 * scale, 0, Math.PI * 2); ctx.fill()
        ctx.beginPath(); ctx.moveTo(37 * scale, 35 * scale); ctx.quadraticCurveTo(41 * scale, 39 * scale, 46 * scale, 35 * scale)
        ctx.strokeStyle = "#68452f"; ctx.lineWidth = 1.7 * scale; ctx.stroke()
    }

    function paintPrecipitation(ctx, kind, centerX, top, scale) {
        let count = kind === "hail" || kind === "sleet" ? 5 : 3
        for (let index = 0; index < count; index += 1) {
            let x = centerX + (index - (count - 1) / 2) * (count > 3 ? 9 : 13) * scale
            if (kind === "snow") {
                drawSnowflake(ctx, x, top + 5 * scale, 5 * scale)
            } else if (kind === "hail") {
                let radius = (2.6 + (index % 2) * .7) * scale
                ctx.fillStyle = index % 2 ? "#d9f6ff" : "#b9e6f2"; ctx.strokeStyle = "#5f91a5"; ctx.lineWidth = 1.3 * scale
                ctx.beginPath()
                for (let side = 0; side < 6; side += 1) {
                    let angle = side * Math.PI / 3 + index * .28
                    let px = x + Math.cos(angle) * radius
                    let py = top + 5 * scale + Math.sin(angle) * radius
                    if (side === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                }
                ctx.closePath(); ctx.fill(); ctx.stroke()
                ctx.fillStyle = "#ffffff"; ctx.beginPath(); ctx.arc(x - radius * .25, top + 4 * scale, radius * .22, 0, Math.PI * 2); ctx.fill()
            } else if (kind === "sleet" && index % 2 === 1) {
                ctx.fillStyle = "#c8eff9"; ctx.strokeStyle = "#5f91a5"; ctx.lineWidth = 1.2 * scale
                ctx.beginPath(); ctx.moveTo(x, top + scale); ctx.lineTo(x + 3.2 * scale, top + 5 * scale); ctx.lineTo(x, top + 9 * scale); ctx.lineTo(x - 3.2 * scale, top + 5 * scale); ctx.closePath(); ctx.fill(); ctx.stroke()
            } else {
                ctx.strokeStyle = kind === "drizzle" ? "#58aee0" : "#258dcc"
                ctx.lineWidth = (kind === "drizzle" ? 2 : 3) * scale
                ctx.lineCap = "round"
                ctx.beginPath(); ctx.moveTo(x + 3 * scale, top); ctx.lineTo(x - 1 * scale, top + 10 * scale); ctx.stroke()
            }
        }
    }

    onPaint: {
        let ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)
        let sx = width / 76
        let sy = height / 64
        let scale = Math.min(sx, sy)
        let ox = (width - 76 * scale) / 2
        let oy = (height - 64 * scale) / 2
        ctx.save(); ctx.translate(ox, oy)
        if (icon === "sun") {
            drawSun(ctx, 38 * scale, 30 * scale, 13 * scale)
        } else if (icon === "moon") {
            drawMoon(ctx, 38 * scale, 29 * scale, 18 * scale)
        } else if (icon === "partly") {
            drawSun(ctx, 25 * scale, 19 * scale, 11 * scale)
            drawCloud(ctx, 15 * scale, 17 * scale, .78 * scale)
        } else if (icon === "moon-cloud") {
            drawMoon(ctx, 24 * scale, 20 * scale, 13 * scale)
            drawCloud(ctx, 15 * scale, 17 * scale, .78 * scale)
        } else if (icon === "wind") {
            drawWindLeaf(ctx, scale)
        } else if (icon === "cold") {
            drawIceCube(ctx, scale)
        } else if (icon === "warning") {
            ctx.fillStyle = "#ffd85a"; ctx.strokeStyle = "#8f5e18"; ctx.lineWidth = 4 * scale
            ctx.beginPath(); ctx.moveTo(38 * scale, 5 * scale); ctx.lineTo(70 * scale, 57 * scale); ctx.lineTo(6 * scale, 57 * scale); ctx.closePath(); ctx.fill(); ctx.stroke()
            ctx.strokeStyle = "#6b4615"; ctx.lineWidth = 5 * scale; ctx.beginPath(); ctx.moveTo(38 * scale, 21 * scale); ctx.lineTo(38 * scale, 40 * scale); ctx.stroke()
            ctx.fillStyle = "#6b4615"; ctx.beginPath(); ctx.arc(38 * scale, 49 * scale, 3 * scale, 0, Math.PI * 2); ctx.fill()
        } else {
            drawCloud(ctx, 3 * scale, 5 * scale, .94 * scale)
            if (icon === "fog") {
                ctx.strokeStyle = "#7896a0"; ctx.lineWidth = 3 * scale; ctx.lineCap = "round"
                ctx.beginPath(); ctx.moveTo(12 * scale, 51 * scale); ctx.lineTo(64 * scale, 51 * scale); ctx.moveTo(20 * scale, 59 * scale); ctx.lineTo(58 * scale, 59 * scale); ctx.stroke()
            } else if (["rain", "drizzle", "snow", "sleet", "hail"].indexOf(icon) >= 0) {
                paintPrecipitation(ctx, icon, 38 * scale, 49 * scale, scale)
            } else if (icon === "storm") {
                ctx.fillStyle = "#ffe04c"; ctx.strokeStyle = "#9b6816"; ctx.lineWidth = 2 * scale
                ctx.beginPath(); ctx.moveTo(39 * scale, 43 * scale); ctx.lineTo(29 * scale, 56 * scale); ctx.lineTo(38 * scale, 56 * scale); ctx.lineTo(33 * scale, 64 * scale); ctx.lineTo(50 * scale, 49 * scale); ctx.lineTo(42 * scale, 49 * scale); ctx.closePath(); ctx.fill(); ctx.stroke()
            }
        }
        ctx.restore()
    }
}
