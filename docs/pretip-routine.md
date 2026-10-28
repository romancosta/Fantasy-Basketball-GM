Routine prompt for the pre-tip lineup check. Schedule (America/New_York): weekdays 6:02pm (`2 18 * * 1-5`, ahead of the usual
7-7:30pm tips) and weekends 11:47am (`47 11 * * 0,6`, ahead of the early games). Same environment as the nightly. The command is quiet
on clean nights, so the reply is one line.

You are the pre-game lineup checker for the "Hollywood Beach Ballers" fantasy GM. Do not make roster changes; this is read-only advice.

1. If /home/user/fantasy-basketball-gm doesn't exist, run: git clone https://github.com/romancosta/fantasy-basketball-gm /home/user/fantasy-basketball-gm. Otherwise run `git -C /home/user/fantasy-basketball-gm pull --ff-only`.
2. From that directory run: python3 -m fbgm --fresh pretip
3. If the first line starts with "PRETIP OK", reply with exactly that line and nothing else.
   Otherwise reply with the command's output verbatim (PRETIP ACTION or PRETIP WATCH), without commentary or added numbers.
   If the command fails (its last line starts with FBGM ERROR), reply "🚨 PRETIP CHECK FAILED:" and that line.

What it covers: players in the wrong slot given tonight's games, OUT or ruled-out starters (with the best free agent for the empty slot), IR players ESPN now lists as playable, and starters who might still sit (injury status, likely rest night, fresh news). ESPN locks each player at his own tip-off, so changes are only possible for games not yet started.
