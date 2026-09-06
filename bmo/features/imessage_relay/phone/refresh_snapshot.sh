#!/var/jb/bin/sh
set -eu

source_root=/private/var/mobile/Library/SMS
relay_root=/private/var/imessage-relay-chroot
next_snapshot=$relay_root/.SMS.next
current_snapshot=$relay_root/SMS
previous_snapshot=$relay_root/.SMS.previous
lock_directory=/private/var/run/imessage-relay-snapshot.lock

install_tool=/var/jb/usr/bin/install
cp_tool=/var/jb/usr/bin/cp
find_tool=/var/jb/usr/bin/find
sha_tool=/var/jb/usr/bin/sha256sum
chown_tool=/var/jb/usr/sbin/chown
chmod_tool=/var/jb/usr/bin/chmod
mv_tool=/var/jb/usr/bin/mv
rm_tool=/var/jb/usr/bin/rm
mkdir_tool=/var/jb/usr/bin/mkdir
id_tool=/var/jb/usr/bin/id

if ! "$mkdir_tool" "$lock_directory" 2>/dev/null; then
    exit 0
fi

cleanup() {
    if [ -d "$next_snapshot" ]; then
        "$rm_tool" -r -- "$next_snapshot"
    fi
    "$rm_tool" -d -- "$lock_directory" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

relay_gid="$("$id_tool" -g pi-bmo)"
test -d "$relay_root"
test -d "$source_root/Attachments"
test -z "$("$find_tool" "$source_root/Attachments" -type l -print -quit)"
for database_name in sms.db sms.db-wal sms.db-shm; do
    test -r "$source_root/$database_name"
done

if [ -e "$next_snapshot" ]; then
    "$rm_tool" -r -- "$next_snapshot"
fi
"$install_tool" -d -o 0 -g 0 -m 0700 "$next_snapshot"

(
    cd "$source_root"
    "$sha_tool" sms.db sms.db-wal sms.db-shm > "$next_snapshot/.db.sha256"
    "$find_tool" Attachments -type f \
        -exec "$sha_tool" '{}' \; > "$next_snapshot/.attachments.sha256"
)

"$cp_tool" -a --reflink=auto \
    "$source_root/Attachments" \
    "$next_snapshot/Attachments"

(
    cd "$source_root"
    "$sha_tool" -c "$next_snapshot/.db.sha256" >/dev/null 2>&1
    if [ -s "$next_snapshot/.attachments.sha256" ]; then
        "$sha_tool" -c "$next_snapshot/.attachments.sha256" >/dev/null 2>&1
    fi
)

"$cp_tool" --reflink=auto --preserve=mode,timestamps \
    "$source_root/sms.db" \
    "$source_root/sms.db-wal" \
    "$source_root/sms.db-shm" \
    "$next_snapshot/"

(
    cd "$source_root"
    "$sha_tool" -c "$next_snapshot/.db.sha256" >/dev/null 2>&1
    if [ -s "$next_snapshot/.attachments.sha256" ]; then
        "$sha_tool" -c "$next_snapshot/.attachments.sha256" >/dev/null 2>&1
    fi
)
(
    cd "$next_snapshot"
    "$sha_tool" -c .db.sha256 >/dev/null 2>&1
    if [ -s .attachments.sha256 ]; then
        "$sha_tool" -c .attachments.sha256 >/dev/null 2>&1
    fi
)
"$rm_tool" -- \
    "$next_snapshot/.db.sha256" \
    "$next_snapshot/.attachments.sha256"

"$chown_tool" -R "0:$relay_gid" "$next_snapshot"
"$find_tool" "$next_snapshot" -type d -exec "$chmod_tool" 0550 '{}' +
"$find_tool" "$next_snapshot" -type f -exec "$chmod_tool" 0440 '{}' +

if [ -e "$previous_snapshot" ]; then
    "$rm_tool" -r -- "$previous_snapshot"
fi
if [ -e "$current_snapshot" ]; then
    "$mv_tool" "$current_snapshot" "$previous_snapshot"
fi
if ! "$mv_tool" "$next_snapshot" "$current_snapshot"; then
    if [ ! -e "$current_snapshot" ] && [ -e "$previous_snapshot" ]; then
        "$mv_tool" "$previous_snapshot" "$current_snapshot"
    fi
    exit 1
fi

trap - EXIT INT TERM
"$rm_tool" -d -- "$lock_directory" 2>/dev/null || true
exit 0
