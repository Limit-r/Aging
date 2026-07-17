$text = [System.IO.File]::ReadAllText('d:\Aging\app\ui\main_window.py', [System.Text.Encoding]::GetEncoding(65001))
$lines = $text -split "`n"
$count = 0
for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match '\?' -and $lines[$i] -match '[\uFFFD]') {
        $count++
        'L{0}: {1}' -f ($i+1), $lines[$i]
    }
}
'---'
'Total corrupted lines: ' + $count
