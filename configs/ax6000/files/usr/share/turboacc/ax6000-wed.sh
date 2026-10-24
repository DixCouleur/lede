#!/bin/sh
# Save Turbo ACC's WED choice for the next driver probe, preserving other options.
set -eu
case "${1:-}" in Y|N) target=$1 ;; *) exit 2 ;; esac
module_config=${AX6000_MODULES_CONF:-/etc/modules.conf}
input=$module_config
[ -f "$input" ] || input=/dev/null
updated=$(awk -v target="$target" '
  /^[ \t]*options[ \t]+mt7915e([ \t]|$)/ {
    line=$0
    comment=index(line, "#")
    suffix=""
    if (comment) {
      suffix=substr(line, comment)
      line=substr(line, 1, comment-1)
    }
    gsub(/(^|[ \t]+)wed_enable=[^ \t#]+/, "", line)
    if (!found) {
      line=line " wed_enable=" target
      if (suffix != "") line=line " "
      found=1
    }
    print line suffix
    next
  }
  { print }
  END { if (!found) print "options mt7915e wed_enable=" target }
' "$input")
[ "$updated" != "$(cat "$input")" ] || exit 0
temporary=$(mktemp "$module_config.XXXXXX")
trap 'rm -f "$temporary"' 0
printf '%s\n' "$updated" > "$temporary"
chmod 0644 "$temporary"
mv -f "$temporary" "$module_config"
