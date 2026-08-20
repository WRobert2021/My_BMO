import QtQuick

Canvas {
    id: root
    property color fillColor: "#ffe34f"
    property color outlineColor: "#9b6816"

    onFillColorChanged: requestPaint()
    onOutlineColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    Component.onCompleted: requestPaint()

    onPaint: {
        let ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)
        ctx.save()
        ctx.scale(width / 56, height / 78)
        ctx.lineJoin = "round"
        ctx.fillStyle = root.fillColor
        ctx.strokeStyle = root.outlineColor
        ctx.lineWidth = 4
        ctx.beginPath()
        ctx.moveTo(31, 3)
        ctx.lineTo(8, 42)
        ctx.lineTo(27, 40)
        ctx.lineTo(19, 73)
        ctx.lineTo(49, 30)
        ctx.lineTo(32, 32)
        ctx.closePath()
        ctx.fill()
        ctx.stroke()
        ctx.restore()
    }
}
