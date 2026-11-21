# Sourced by tools/*. Override with env: MEDIASTICK_HOST, MEDIASTICK_KEY.
HOST=${MEDIASTICK_HOST:-mediastick.local}
KEY=${MEDIASTICK_KEY:-$HOME/.ssh/mediastick}
DEST=/opt/media-stick
SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o ConnectTimeout=8 "media@$HOST")
