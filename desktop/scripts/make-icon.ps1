# Draws the app icon (assets/icon.png, 512x512): a glowing orb in the app's accent colors.
# Run once: powershell -ExecutionPolicy Bypass -File scripts/make-icon.ps1
Add-Type -AssemblyName System.Drawing
$size = 512
$bitmap = New-Object System.Drawing.Bitmap $size, $size
$g = [System.Drawing.Graphics]::FromImage($bitmap)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.Clear([System.Drawing.Color]::Transparent)

# Dark rounded tile
$tile = New-Object System.Drawing.Drawing2D.GraphicsPath
$r = 110
$tile.AddArc(16, 16, $r, $r, 180, 90); $tile.AddArc($size - 16 - $r, 16, $r, $r, 270, 90)
$tile.AddArc($size - 16 - $r, $size - 16 - $r, $r, $r, 0, 90); $tile.AddArc(16, $size - 16 - $r, $r, $r, 90, 90)
$tile.CloseFigure()
$g.FillPath((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 8, 9, 14))), $tile)

# Soft halo, then the orb (cyan center fading to violet)
$halo = New-Object System.Drawing.Drawing2D.GraphicsPath
$halo.AddEllipse(76, 76, 360, 360)
$haloBrush = New-Object System.Drawing.Drawing2D.PathGradientBrush $halo
$haloBrush.CenterColor = [System.Drawing.Color]::FromArgb(120, 90, 209, 255)
$haloBrush.SurroundColors = @([System.Drawing.Color]::FromArgb(0, 122, 92, 255))
$g.FillPath($haloBrush, $halo)

$orb = New-Object System.Drawing.Drawing2D.GraphicsPath
$orb.AddEllipse(136, 136, 240, 240)
$orbBrush = New-Object System.Drawing.Drawing2D.PathGradientBrush $orb
$orbBrush.CenterPoint = New-Object System.Drawing.PointF 230, 220
$orbBrush.CenterColor = [System.Drawing.Color]::FromArgb(255, 200, 245, 255)
$orbBrush.SurroundColors = @([System.Drawing.Color]::FromArgb(255, 122, 92, 255))
$g.FillPath($orbBrush, $orb)

$out = Join-Path $PSScriptRoot "..\assets\icon.png"
$bitmap.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bitmap.Dispose()
"icon saved: $out"
