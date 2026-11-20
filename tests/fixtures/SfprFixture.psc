ScriptName SfprFixture extends Quest
{ A made-up script for sf-papyrus-ref's tests. It is our own code, not Bethesda's. }

Actor Property Target Auto

Function Run()
	Debug.Trace("trace") ; DebugOnly (allowed in one test)
	Debug.Notification("note") ; DebugOnly
	Int i = 0
	While i < 3
		Utility.Wait(0.1) ; Latent inside a loop
		i += 1
	EndWhile
	Utility.Wait(0.1) ; Latent, not in a loop: no finding
	Game.Warning("beta") ; BetaOnly
	Target.MoveTo(Target) ; inherited from ObjectReference: Latent, not in a loop
	(Target as ObjectReference).Disable() ; cast
	Helper()
EndFunction

Function Helper()
	; Debug.MessageBox("commented out: no finding")
	String s = "Debug.Notification(not a call)"
EndFunction

Int Property Count
	Int Function Get()
		Return 0
	EndFunction
	Function Set(Int aiValue)
		Debug.MessageBox("set") ; DebugOnly, inside a property's Set handler
	EndFunction
EndProperty
