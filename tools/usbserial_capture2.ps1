# usbserial_capture2.ps1 -Out FILE [-Seconds N]: capture the iOS kernel USB serial console
# (QcomXnuUsbDebug / CDC ACM, VID 1209 PID 316D) into FILE.
#
# Difference from usbserial_capture.ps1: Find-Port uses Get-PnpDevice, because on this host
# the device shows up in Get-PnpDevice but NOT in Win32_PnPEntity (CIM). The old script
# therefore waited forever even while the port was present.
param(
	[Parameter(Mandatory = $true)][string]$Out,
	[int]$Seconds = 600
)

$deadline = (Get-Date).AddSeconds($Seconds)
$events = "$Out.events"
$stream = [System.IO.File]::Open($Out, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write,
	[System.IO.FileShare]::Read)
function Note([string]$text) {
	$line = "{0:HH:mm:ss.fff} {1}" -f (Get-Date), $text
	Add-Content -Path $events -Value $line -Encoding utf8
}

function Find-Port {
	# Get-PnpDevice sees the device even when CIM does not. FriendlyName is like
	# "USB Serial Device (COMx)"; fall back to InstanceId if no COM in the name.
	$d = Get-PnpDevice -Class Ports -ErrorAction SilentlyContinue |
		Where-Object { $_.InstanceId -like 'USB\VID_1209&PID_316D*' -and $_.Status -eq 'OK' } |
		Select-Object -First 1
	if ($d -and $d.FriendlyName -match '\((COM\d+)\)') { return $Matches[1] }
	return $null
}

Note "waiting for VID_1209 PID_316D (Get-PnpDevice) until $($deadline.ToString('HH:mm:ss'))"
$buffer = New-Object byte[] 65536
try {
	while ((Get-Date) -lt $deadline) {
		$name = Find-Port
		if (-not $name) { Start-Sleep -Milliseconds 400; continue }
		$port = New-Object System.IO.Ports.SerialPort $name, 115200
		$port.ReadTimeout = 150
		$port.DtrEnable = $true
		$port.RtsEnable = $true
		$opened = $false
		for ($try = 0; $try -lt 10 -and -not $opened; $try++) {
			try { Start-Sleep -Milliseconds 400; $port.Open(); $opened = $true } catch { Note "open $name failed: $($_.Exception.Message)" }
		}
		if (-not $opened) { continue }
		Note "opened $name (DTR=$($port.DtrEnable))"
		$total = 0
		try {
			while ((Get-Date) -lt $deadline) {
				try {
					$n = $port.Read($buffer, 0, $buffer.Length)
					if ($n -gt 0) { $stream.Write($buffer, 0, $n); $stream.Flush(); $total += $n }
				} catch [System.TimeoutException] { }
			}
		} catch {
			Note "$name gone after $total bytes: $($_.Exception.Message)"
		} finally {
			try { $port.Close() } catch { }
		}
	}
} finally {
	$stream.Close()
	Note "done"
}
