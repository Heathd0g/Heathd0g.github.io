-- Blog Publisher: drop a markdown file on this app to publish it to heath.dog/blog.
-- Double-click it to pick a file instead. The work is done by publish.py beside this app.

property scriptPath : POSIX path of ((path to home folder as text) & "Documents:heathdog-site:tools:blog_publisher:publish.py")

on run
	set f to choose file with prompt "Pick a markdown file to publish to heath.dog/blog" of type {"md", "markdown", "txt", "public.plain-text"}
	publishFile(f)
end run

on open droppedItems
	repeat with f in droppedItems
		publishFile(f)
	end repeat
end open

on publishFile(f)
	set py to "/usr/bin/python3"
	try
		do shell script "test -x /opt/homebrew/bin/python3"
		set py to "/opt/homebrew/bin/python3"
	end try
	try
		do shell script "export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin; " & quoted form of py & " " & quoted form of scriptPath & " --gui " & quoted form of (POSIX path of f)
	on error errMsg number errNum
		if errNum is not 1 then display dialog "Blog Publisher hit an error:" & return & return & errMsg with title "Blog Publisher" buttons {"OK"} default button "OK" with icon stop
	end try
end publishFile
