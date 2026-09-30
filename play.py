#!/usr/bin/env python3
"""
Playable games, driven entirely through the API.

Every game here is stateful but serverless: a client starts a game, gets a
session id, and sends moves. State lives in the server's LRU cache, so a game
survives across requests without a database and disappears when it is evicted -
which is the right trade for a bot: the bot keeps the session id in its own
memory, and a forgotten game just expires.

What is here, and why each one works as a REST call:

  tic-tac-toe   new game, place a mark, read the board. The bot renders the
                board as monospace text; the API only owns the rules.
  wordguess     pick a word, then guess letter by letter with hints.
  riddle        asah otak: a riddle, a hint ladder, and a reveal.
  brain         a few genuinely different logic puzzles, so the bot menu is
                not just one puzzle wearing four names.
  gacha         weighted random draw with pity counter, so a bot can sell
                "you pulled SSR" without any client-side logic.
  dice          dnd dice notation parser, so `?dice=2d6+3` just works.
  puzzle        15-puzzle, solvable-state check and a hint (manhattan).
  minesweeper   board generation with a guaranteed-safe first click.

Nothing here calls out to the network, and nothing needs an account.
"""

import hashlib
import random
import re
import string
import time

# How long a game may sit untouched before the cache drops it. Games are cheap
# to recreate and nobody wants a stale session from yesterday.
GAME_TTL = 6 * 3600

MAX_TTT_SIZE = 15          # a 15x15 tictactoe is still tractable, 25x25 is not
MAX_WORD_LEN = 12
MIN_WORD_LEN = 3


# --------------------------------------------------------------------------
# word list
# --------------------------------------------------------------------------

# A few hundred common English words, chosen short and unambiguous so a
# hangman-style game is actually winnable. Kept inline because a bot should
# not depend on a wordlist being downloadable at boot.
WORDS = """
abacus able about above absent accept access acid acorn across action active
actor adapt add adobe adopt adult advance advice affair afford afraid after
again agent agree ahead aim air alarm album alert alien alive allow almond
alone along alpha already also always amber amaze among amount ample anchor
angel anger angle animal answer ant anvil anxious any apart apple apply april
arcade arch arctic argue arise arm army aroma around arrow art ashes aside
ask asleep aspect assist atlas atom attach attack attempt attend august aunt
author auto autumn avoid awake award aware away awful axis
baby bacon badge bagel baker balance ball band bank banner barley barn barrel
basil basin basket batch bath battery beach beacon bean bear beard beast beaver
bed bee beef beetle begin bell belt bench bend berry bicycle bill bind bird
birth bison bitter black blade blanket blast blaze blend blimp blink block
blond blood bloom blouse blue blush board boat bold bolt bond bone bonus book
boost border born borrow bottle bottom boulder bounce bound bowl box brace
braid brain brake branch brass brave bread break breeze brick bridge brief
bright bring brisk broad broken bronze brook broom brown brush bubble bucket
buddy buffalo bugle build bulb bulk bull bumper bunch bundle bunker burden
butter button buzz
cabin cable cactus cage cake calm camel camera camp canal candle candy canoe
canvas canyon cape captain car carbon cargo carpet carrot cart carve case
cash casino castle cat catch cattle cave cedar ceiling cell cement census
center cereal chain chair chalk champion chance change chant chaos chapel
charge charm chart chase cheek cheer cheese chef cherry chess chest chew
chicken chief child chili chill chimney chip chisel chocolate choice choir
chop chord chorus chosen chrome chunk cider cigar cinema circle circus citrus
city civic civil claim clamp clan clap clash class claw clay clean clerk
cliff climb clinic clip clock close cloth cloud clover clown club clue clump
cluster coach coast coat cobra cocoa code coffee coil coin cold collar college
colony color column comb combat comedy comet comfort comic common compass
concert concrete condor cone connect consent contact contest context control
convert cook cool copper copy coral cord core corn correct cost cottage cotton
cougar council counter country county courage course court cousin cover
coyote cozy crab crack cradle craft crane crash crate crawl crayon cream
create credit creek crest crew cricket crime crisp critic crop cross crowd crown
crucial cruise crumb crunch crush crystal cube culture cup curious current
curtain curve cushion custom cycle cylinder cypress
dagger daily dairy dam dance danger dapper daring dash data dawn day deal
debate debris decade december decide deck declare decline decode deep deer
defend define degree delay delete deliver delta demand denim dense dental
depart depend deposit depth desert design desk detail detect develop device
dew diagram dial diamond diary dice diesel diet differ digital dignity
dilute dinner dinosaur direct dirt disarm disk display distant ditch dive
divide dizzy dock doctor dodge dolphin domain donate donkey double doubt
dozen draft dragon drain drama draw dream dress drift drill drink drive drop
drum duck dune dusk dust duty dwarf dwell dynamic
eager eagle early earn earth easel ease east easy eat echo eclipse edge
edit effort eight either elbow elder elect elegant element elephant elevate
elite elope embark ember embrace emerald emotion employ empty enable enact
enamel enchant encode endless endure enemy energy enforce engage engine enjoy
enlarge enroll ensure enter entire entry envelope envy epic equal equip era
erase erode errand error erupt escape escort essay estate eternal ethics
evade evening event ever every exact exam example exceed exchange excite
exclaim exclude excuse exempt exhale exhibit exile exist exit expand expert
expire explain explore export express extend extra extreme eye
fabric facade factor fade fair faith falcon fall false fame family famous
fancy fang fantasy farm fashion fasten fate fatigue fault favor feast feather
feature fee feed feel fellow fence fern ferry fever fiber fiction field fierce
fifty fig figure file filter final finance find fine finger finish fire firm
first fiscal fish fist fitting fix flag flame flash flat flavor flee fleet flesh
flight flint float flock flood floor flour flow flower fluid flush flute fly
foam focus fog fold folk follow fond food foot force forecast forest forge fork
form fortune forum forward fossil foster found fountain four fox frame
frank fraud free freeze freight frequent fresh friend fringe frog front frost
frown fruit fudge fuel full fun fund fungus funnel fur furnace fury fuse
future
gadget gain galaxy gallery game gap garage garden garlic gas gate gather gauge
gaze gear gem general genius gentle genuine gesture ghost giant gift giggle
ginger giraffe girl give glad glance glare glass glaze gleam glide glimpse
glint globe gloom glory glove glow glue goal goat gold golf gone good goose
gorge gospel gossip govern gown grab grace grade grain grant grape graph
grasp grass grateful grave gravel gray graze great green greet grid grief
grill grin grip grit groan grocer ground group grove grow growl grumble
guard guess guest guide guild guilt guitar gulf gully gum gust gutter
habit hail hair half hall halt hammer hand handle hang harbor harm harsh
harvest hasty hatch hate haul haunt haven hazard head heal health heap hear
heart heat heavy hedge heel height heir helmet help hem herd hero hidden hide
high hike hill hint hip hire history hobby hockey hold hole holiday hollow
honest honey honor hope horizon horn horse hospital host hotel hour house
hover howl human humble humor hunt hurry hurt husband hush hut
icon idea ideal identify idle ignore image imagine impact imply import impose
impress improve impulse inch include income index indoor industry infant
inform inherit inject injure ink inland inmate inner input insect inside
insist inspect inspire install intact intend invite iris island issue item
ivory
jacket jail jam jar jaw jazz jealous jeans jelly jewel job join joke jolly
journal journey joy judge juice july jump june jungle junior junk jury just
kale kapok kayak keen keep kennel kernel kettle key kick kid kidney kind
kingdom kiss kit kitchen kite kitten knee knife knock knot know koala
label labor lace ladder lady lagoon lake lamb lamp land lane language
lantern lap large laser last late laugh lava law lawn layer lazy leader leaf
league leak lean leap learn lease leash least leather leave lecture ledge
lemon lend length lens leopard lesson letter level liberty library license
lid life lift light like lilac lily limb lime limit line linen link lion
liquid list listen live lizard load loaf loan lobby local locate lock lodge
loft logic lonely long look loop loose lord lose lot loud lounge love
loyal lucky lumber lunar lunch lung luxury lyric
machine mad magic magnet maid mail main major make male mall mammal man
manage mane manner mansion manual many map marble march margin marine market
marsh mask mason master mat match material math matter mattress max maze meadow
meal mean measure meat medal media medium meet melody melt memory mend menu
mercy merge merit merry mesh message metal method middle midnight might mild
mile milk mill mind mine mingle mint minute mirror miss mist mix moat
mobile model modem moist mold moment money monitor monk month mood moon moral
more morning mosaic moss most motel moth mother motion motor mountain mouse
mouth move movie much mud muffin mule multiply muscle museum mushroom music
must mutual mystery myth
nail naked name napkin narrow nation native nature navy near neat neck
need needle negative neglect neighbor neither nerve nest net network
neutral never new news next nice niche nickel niece night nine noble noise
none noodle nook normal north nose note notice novel now number nurse nut
oak oasis oath obey object oblige observe obtain obvious occur ocean october
odd odor offer office often oil okay old olive omit once one onion online only
open opera opinion oppose option orange orbit orchard order organ origin
ostrich other otter ought ounce out outer output outside oval oven over owl
own oxygen oyster
pace pack paddle page pain paint pair palace pale palm pan panda panel
panic pants papaya paper parade parent park parrot parsley part party pass
past pasta patch path patient patrol pause pave paw peace peach peak
peanut pear pearl pebble peck pedal peel peer pelican pen pencil penny people
pepper per perch perfect perform perfume perhaps period permit person pet
phone photo phrase piano pick picnic picture piece pig pigeon pill pillar
pilot pin pine pink pioneer pipe pistol pitch pity place plain plan plant
plastic plate play plaza pleasant please pledge plenty plot plug plum plunge
plus pocket poem poet point poison poke polar pole polish polite poll pond
pony pool poor popcorn pop porch pork port portrait pose position post pot
potato pottery pouch pound pour poverty powder power praise prank pray preach
precise predict prefer prepare present preserve press pretty prevent price
pride primary prince print prior prison private prize probe problem proceed
process produce profile profit program project promise proof proper protect
proud prove provide public pudding puddle puff pull pulse pump pumpkin
punch pupil puppy purple purse push put puzzle
quail quarter queen query quest question quick quiet quilt quit quiver quiz
quote
rabbit raccoon race rack radar radio raft rage raid rail rain raise rally
ramp ranch random range rank rapid rare rash rat rate rather ratio rattle
raven raw ray razor reach react read ready real reason rebel recall receive
recent recipe record recover recruit red reduce reef refer refine reflect
reform refuge refund refuse regard region regret regular reject relax release
relief rely remain remark remedy remind remote remove render renew rent repair
repeat replace reply report request rescue research reserve resist resolve
resource respect respond rest result retire return reveal revenge review
reward rhythm rib ribbon rice rich ride ridge rifle right rigid rim ring
rinse ripe rise risk ritual rival river road roast robin robot rock rocket
rod role roll roof room root rope rose rough round route royal rubber ruby
rude rug ruin rule rumor run rural rush rust
sack sacred saddle safe sail saint salad salmon salon salt same sample sand
sane satin sauce save saw scale scan scarf scatter scene scent school science
scissors scorpion scout scrap screen screw script sea seal search season
seat second secret section secure seed seek seem segment seize seldom select
self sell senate send senior sense sentence series servant serve service
session settle seven sew shade shadow shaft shake shallow shape share sharp
shave shed sheep sheet shelf shell shelter shine ship shirt shiver shock shoe
shoot shop shore short should shoulder shout show shrimp shrink shuffle shy
sick side siege sigh sight sign signal silent silk silly silver similar simple
since sing single sink sir siren sister sit site situation size skate sketch
ski skill skin skip skirt skull sky slab slam sleep slender slide slight slim
slip slip slope slot slow slug slump small smart smash smell smile smoke
smooth snake snap snow soap soccer social sock soda sofa soft soil solar
soldier sole solid solve some song soon sorry sort soul sound soup source
south space spare spark speak special speed spell spend sphere spice spider
spike spill spin spirit splash split spoil spoke sponge spoon sport spot
spouse spray spread spring sprinkle square squeeze squid stable stack staff
stage stair stamp stand star starch start state station stay steady steak
steal steam steel steep steer stem step stereo stick stiff still sting stir
stitch stock stomach stone stool stop store storm story stove strange straw
stream street stretch strict strike string strip stripe strong struggle
student studio study stuff stumble style subject submit subtle succeed such
sudden suffer sugar suggest suit summer summit sun super supply support
suppose surge surprise surround survey swallow swamp swan swarm swear sweat
sweep sweet swift swim swing switch sword symbol symptom syrup system
table tackle tact tag tail talent talk tall tank tape target task taste
tattoo taxi tea teach team tear tease teeth telegram tell temper temple tenant
tennis tent term terrace terrible test text thank that theme theory there
thermal thick thief thigh thin thing think third thirty this thorn thought
three thrive throat throne throw thumb thunder ticket tide tidy tie tiger
tight tile timber time tiny tip tired tissue title toad toast today toe
together toil token tomato tomorrow tone tongue tonight tool tooth top topic
torch tornado tortoise toss total touch tough tour tourist towel tower town
toy trace track trade traffic trail train trait transfer trap trash travel
tray treat tree trend trial tribe trick trigger trim trip triumph trolley
troop trophy trouble trout truck true trunk trust truth try tube tuck tuna
tune tunnel turkey turn turtle twelve twenty twice twig twin twist two type
ugly umbrella uncle under undo unfold uniform union unique unit universe
unless unlock until unusual upon upper upset urban urge use useful usher
usual utensil utility
vacant vague valid valley value valve van vanish vapor variety vase vast
vault vegetable vehicle veil vein velvet vendor venture verb verdict verse
very vessel veteran vibrate victory video view village vinegar vintage viola
violet violin virtual virtue virus visit vital vivid vocal voice volcano
volume vote voyage vulgar
wade wag wagon waist wait wake walk wall walnut wander want war ward
warm warn wash wasp waste watch water wave wax way weak wealth weapon
wear weasel weather weave wedding weed week weigh weird welcome well west
wet whale what wheat wheel when where which while whip whisper whistle white
whole whom why wick wide widow width wife wild will willow win wind window
wine wing wink winner winter wipe wire wisdom wise wish witness wizard wolf
woman wonder wood wool word work world worm worry worth wound wrap wrench
wrist write wrong
yard yarn yawn year yeast yell yellow yes yesterday yet yield yoke yolk
young your youth
zebra zero zigzag zinc zone zoo
""".split()

# Indonesian words, for a localised variant of the word game. Curated the
# same way as the English list: common, short, and unambiguous to spell.
WORDS_ID = """
ada adalah agar akan aku aman anda antara apa apabila asal atas atau awal
bagai bagaimana bagi bahkan bahwa baik bakal banyak bapak baru bawah banyak
batu belum benar berada berapa berbagai berikut bersama bertanya bertemu besar
bila bisa boleh bukan buah bulan cukup cuma dahulu dalam dan dapat dari
daripada dekat demi demikian dengan depan di dia dua dulu entah guna hal hampir
hanya hari harus hendak hingga ia ialah ini itu jadi jangan jika juga jumlah
justru kala kalau kali kalian kami kamu kan kapan karena kata kau kecil ketika
kini kita kurang lagi lain lalu lama lebih maka makin malah mampu mana masa
masih mau melakukan melalui memang memberi membuat memiliki menjadi menuju
menurut mereka merupakan meski misal mungkin namun oleh pada padahal paling
para pasti pernah pertama pihak pula pun punya saat saja sama sambil sampai
sangat satu saya sebagai sebelum sebenarnya sedang sehingga sejak sekali
sekarang selain selalu selama seluruh semacam semakin semua semula sendiri
seorang sepanjang seperti serta sesuatu setiap siapa sini suatu sudah supaya
tanpa tapi telah tentang tentu terhadap terjadi termasuk tersebut tetapi tidak
tiga tinggi turut untuk usai waktu walau yaitu yakni
""".split()
WORDS_ID = [w for w in WORDS_ID if w.isalpha()]


# --------------------------------------------------------------------------
# tiny session store
# --------------------------------------------------------------------------

class Sessions(object):
    """TTL + LRU store for game state.

    The API server already has a cache module with the same shape; this is a
    small standalone copy so ``play.py`` has no import-time dependency on the
    HTTP layer and can be unit-tested on its own.
    """

    def __init__(self, max_items=2000, ttl=GAME_TTL):
        self.max_items = max_items
        self.ttl = ttl
        self._items = {}
        self._order = []

    def _touch(self, sid):
        try:
            self._order.remove(sid)
        except ValueError:
            pass
        self._order.append(sid)

    def put(self, sid, value):
        now = time.time()
        prev = self._items.get(sid)
        if prev:
            prev["value"] = value
            prev["touched"] = now
        else:
            self._items[sid] = {"value": value, "touched": now}
            self._order.append(sid)
        self._touch(sid)
        while len(self._order) > self.max_items:
            self._items.pop(self._order.pop(0), None)
        return sid

    def get(self, sid):
        rec = self._items.get(sid)
        if not rec:
            return None
        if time.time() - rec["touched"] > self.ttl:
            self._items.pop(sid, None)
            try:
                self._order.remove(sid)
            except ValueError:
                pass
            return None
        self._touch(sid)
        return rec["value"]

    def drop(self, sid):
        self._items.pop(sid, None)
        try:
            self._order.remove(sid)
        except ValueError:
            pass
        return True

    def count(self):
        return len(self._items)


def new_id(prefix, salt=""):
    """Short, collision-resistant, and readable in a chat log."""
    h = hashlib.sha256(("%s%s%s%.6f" % (prefix, salt, time.time(),
                                       random.random())).encode()).hexdigest()
    return prefix + "_" + h[:12]


# --------------------------------------------------------------------------
# tic-tac-toe
# --------------------------------------------------------------------------

def ttt_board_text(board, size, marks=("X", "O")):
    """Render the board the way a chat bot wants to print it.

    3x3 stays compact one line per row; larger boards get a frame so the
    columns line up when a human reads them in a monospace Telegram message.
    """
    def cell(v):
        return v or "."

    if size == 3:
        rows = [" ".join(cell(c) for c in board[r * size:(r + 1) * size])
                for r in range(size)]
        return "\n".join(rows)

    width = 2 * size + 1
    sep = "+" + ("---+" * size)
    out = [sep]
    for r in range(size):
        row = "| " + " | ".join(cell(c) for c in
                               board[r * size:(r + 1) * size]) + " |"
        out.append(row)
        out.append(sep)
    return "\n".join(out)


def ttt_winner(board, size):
    """Return 'X', 'O' or None. X moves first, so 'O' is the win for a
    single-mark game that started as X."""
    lines = []
    n = size
    for r in range(n):
        lines.append([r * n + c for c in range(n)])
    for c in range(n):
        lines.append([r * n + c for r in range(n)])
    lines.append([r * n + r for r in range(n)])
    lines.append([r * n + (n - 1 - r) for r in range(n)])
    for line in lines:
        vals = [board[i] for i in line]
        if vals[0] and vals[0] == vals[1] == vals[2]:
            return vals[0]
    return None


def ttt_full(board):
    return all(board)


def new_tictactoe(size=3, first="X", opener=None):
    size = max(3, min(int(size), MAX_TTT_SIZE))
    return {
        "game": "tictactoe",
        "size": size,
        "board": [None] * (size * size),
        "turn": first,
        "first": first,
        "other": "O" if first == "X" else "X",
        "winner": None,
        "over": False,
        "moves": 0,
        "opened": time.time(),
    }


def ttt_play(state, index, mark=None, zero_based=False):
    """Place a mark and return (state, message).

    Cells are 1-based by default, because a chat bot hands the user "cells
    1-9" and should not have to convert. Callers that think in array indices
    pass ``zero_based=True``; accepting both conventions at once is ambiguous
    (a 0-based 4 and a 1-based 4 are different cells, and 4 is in range either
    way), so one has to be chosen explicitly.
    """
    if state.get("over"):
        return state, "This game is already over."
    n = state["size"]
    cells = n * n
    if index is None or index == "":
        return state, "No cell given."
    try:
        i = int(index)
    except (TypeError, ValueError):
        return state, "Cell must be a number."
    if zero_based:
        if not (0 <= i < cells):
            return state, "Cell must be between 0 and %d." % (cells - 1)
    else:
        if not (1 <= i <= cells):
            return state, "Cell must be between 1 and %d." % cells
        i -= 1
    if state["board"][i]:
        return state, "Cell %d is already taken." % (i + 1)
    mark = mark or state["turn"]
    if mark not in ("X", "O"):
        return state, "Mark must be X or O."
    state["board"][i] = mark
    state["moves"] += 1
    win = ttt_winner(state["board"], n)
    if win:
        state["winner"] = win
        state["over"] = True
        return state, "%s wins!" % win
    if ttt_full(state["board"]):
        state["over"] = True
        return state, "Draw."
    state["turn"] = state["other"] if mark == state["first"] else state["first"]
    return state, "Placed %s at cell %d." % (mark, i + 1)


# --------------------------------------------------------------------------
# word game
# --------------------------------------------------------------------------

def pick_word(words=None, length=None, rng=random):
    pool = words if words is not None else WORDS
    pool = [w for w in pool
            if w.isalpha() and MIN_WORD_LEN <= len(w) <= MAX_WORD_LEN]
    if length:
        n = int(length)
        exact = [w for w in pool if len(w) == n]
        if exact:
            pool = exact
    return rng.choice(pool).upper()


def new_wordgame(length=None, lang="en", hint=True):
    words = WORDS
    if lang.startswith("id"):
        words = WORDS_ID
    word = pick_word(words, length)
    return {
        "game": "wordguess",
        "lang": lang,
        "word": word,
        "guessed": [],
        "left": set(word) - set("-"),
        "status": "playing",          # playing | won | lost
        "tries": 0,
        "hint_available": bool(hint),
        "opened": time.time(),
    }


def wordgame_state(st, reveal=False):
    word = st["word"]
    if st["status"] == "lost" or (reveal and st["status"] == "won"):
        shown = word
    else:
        shown = "".join(c if (c in st["guessed"] or c == "-") else "_"
                        for c in word)
    return {
        "word_pattern": shown,
        "guessed": sorted(st["guessed"]),
        "remaining": sorted(st["left"] - set(st["guessed"])),
        "tries": st["tries"],
        "status": st["status"],
    }


def wordgame_guess(st, letter):
    st["tries"] += 1
    letter = (letter or "").strip().upper()[:1]
    if not letter.isalpha():
        return st, "Guess must be a single letter."
    if letter in st["guessed"]:
        return st, "You already guessed %s." % letter
    st["guessed"].append(letter)
    if letter in st["left"]:
        st["left"].discard(letter)
        if not st["left"]:
            st["status"] = "won"
            return st, "Correct! The word was %s." % st["word"]
        return st, "Yes, %s is in the word." % letter
    return st, "No, %s is not in the word." % letter


def wordgame_solve(st):
    st["status"] = "lost"
    return st, "The word was %s." % st["word"]


# --------------------------------------------------------------------------
# riddles / asah otak
# --------------------------------------------------------------------------

RIDDLES = [
    ("I have keys but no locks. I have a tongue but cannot talk. "
     "I only travel on your hand.", "keyboard",
     ["What has keys but no doors?", "Typing device"],
     "I have teeth but cannot bite."),
    ("The more you take, the more you leave behind.", "footsteps",
     ["What gets more the more you take?", "Walking"],
     "Every step you take creates one."),
    ("What gets wetter the more it dries?", "towel",
     ["What dries itself?", "Bath item"],
     "It is used exactly when you are wet."),
    ("I speak without a mouth and hear without ears. "
     "I have no body, but I come alive with the wind.", "echo",
     ["What repeats what you say?", "Sound in a canyon"],
     "Try shouting in a valley."),
    ("What has hands but cannot clap?", "clock",
     ["What shows time with hands?", "Wall object"],
     "It has two of them and it ticks."),
    ("What has a head, a tail, but no body?", "coin",
     ["What has two ends and no middle?", "Money"],
     "It is small, flat, and in your pocket."),
    ("What can travel around the world while staying in a corner?", "stamp",
     ["What sits on a letter?", "Postage"],
     "It is glued on the envelope."),
    ("I am tall when I am young and short when I am old. "
     "What am I?", "candle",
     ["What burns down as it lives?", "Wax object"],
     "It has a flame, not legs."),
    ("What has many teeth but cannot bite?", "comb",
     ["What has teeth made of plastic?", "Hair item"],
     "It is used on your head."),
    ("The person who makes it sells it, the person who buys it never "
     "uses it, the person who uses it never knows they are using it. "
     "What is it?", "coffin",
     ["What is sold, bought, and never knowingly used?", "Funeral item"],
     "It is wooden and holds a body."),
    ("What is full of holes but still holds water?", "sponge",
     ["What holds water but is not a cup?", "Bathroom item"],
     "It is soft and porous."),
    ("What has one eye but cannot see?", "needle",
     ["What has a hole and a point?", "Sewing item"],
     "It threads a thread through cloth."),
    ("What breaks yet never falls, and what falls yet never breaks?",
     "day and night", ["What falls but never breaks?", "Night"],
     "Two things, one question."),
    ("The more you run, the less you have behind you. What am I?", "breath",
     ["What do you lose when you run?", "Air from lungs"],
     "It is invisible."),
    ("What goes up but never comes down?", "your age",
     ["What increases every year and never decreases?", "Years"],
     "Everyone has one."),
]

RIDDLES_ID = [
    ("Aku punya kunci tapi nggak punya gembok. Aku punya lidah tapi nggak "
     "bisa bicara. Aku cuma jalan di tanganmu.", "keyboard",
     ["Punya kunci tapi nggak ada pintu?", "Alat ketik"],
     "Dipakai buat ngetik."),
    ("Makin banyak yang diambil, makin banyak yang tertinggal.", "langkah",
     ["Makin diambil makin banyak yang tinggal?", "Berjalan"],
     "Setiap langkah bikin satu."),
    ("Semakin basah semakin kering. Aku apa?", "handuk",
     ["Apa yang mengeringkan dirinya sendiri?", "Perlengkapan mandi"],
     "Dipakai pas kamu basah."),
    ("Aku bicara tanpa mulut dan mendengar tanpa telinga. Aku nggak punya "
     "badan tapi hidup bersama angin.", "gema",
     ["Apa yang mengulang katamu?", "Suara di lembah"],
     "Try berteriak di lembah."),
    ("Aku tinggi waktu muda dan pendek waktu tua. Aku apa?", "lilin",
     ["Apa yang memendek sambil hidup?", "Benda dari lilin"],
     "Punya api, nggak punya kaki."),
    ("Punya gigi tapi nggak bisa gigit. Aku apa?", "sisir",
     ["Punya gigi plastik?", "Alat rambut"],
     "Dipakai di kepala."),
    ("Kalau aku punya kaki, aku tidak punya tubuh. Aku punya kepala tapi "
     "nggak punya overpriced. Aku apa?", "koin",
     ["Aku punya lingkaran tapi nggak ada lubang?", "Uang receh"],
     "Kecil, datar, ada di kantong."),
    ("Orang yang buat aku menjualnya, yang beli nggak pernah pakai, yang "
     "pakai nggak pernah tahu. Aku apa?", "peti jenazah",
     ["Apa yang dijual dan dibeli tapi nggak pernah dipakai?", "Barang kubur"],
     "Dari kayu dan berisi jenazah."),
]



def new_riddle(lang="en", difficulty=None):
    pool = RIDDLES_ID if lang.startswith("id") else RIDDLES
    idx = random.randrange(len(pool))
    q, answer, hints, extra = pool[idx]
    return {
        "game": "riddle",
        "lang": lang,
        "riddle": q,
        "answer": answer,
        "hints": hints,
        "extra_hint": extra,
        "hints_used": 0,
        "solved": False,
        "index": idx,
        "opened": time.time(),
    }


def riddle_hint(st):
    if st["solved"]:
        return st, "Already solved: %s" % st["answer"]
    st["hints_used"] += 1
    if st["hints_used"] <= len(st["hints"]):
        h = st["hints"][st["hints_used"] - 1]
    else:
        h = st["extra_hint"]
    return st, "Hint %d: %s" % (st["hints_used"], h)


def riddle_answer(st, text):
    text = (text or "").strip().lower()
    if not text:
        return st, "Say something."
    ans = st["answer"].lower()
    if text == ans or text in ans or ans in text:
        st["solved"] = True
        return st, "Correct! The answer is %s." % st["answer"]
    return st, "Not quite."


# --------------------------------------------------------------------------
# gacha
# --------------------------------------------------------------------------

# (rarity, weight). Weights are deliberately steep so pulls feel like a game
# rather than a uniform random number.
RARITIES = (
    ("SSR", 1),
    ("SR", 5),
    ("R", 20),
    ("N", 74),
)

PITY_THRESHOLD = 40       # no SSR in this many pulls forces one


def gacha_pool():
    """A fixed pool so a pull is reproducible from the seed in the response."""
    names = WORDS
    out = []
    for rarity, _ in RARITIES:
        for w in names[:200]:
            out.append({"rarity": rarity, "name": w.title()})
    return out


_GACHA = None


def _gacha():
    global _GACHA
    if _GACHA is None:
        pool = gacha_pool()
        weights = []
        for item in pool:
            for r, wt in RARITIES:
                if item["rarity"] == r:
                    weights.append(wt)
                    break
        _GACHA = (pool, weights)
    return _GACHA


def new_gacha(luck=1.0):
    return {
        "game": "gacha",
        "luck": float(luck),
        "since_ssr": 0,
        "pulls": 0,
        "history": [],
        "opened": time.time(),
    }


def gacha_pull(st, count=1, rng=random):
    pool, weights = _gacha()
    try:
        count = max(1, min(int(count), 20))
    except (TypeError, ValueError):
        count = 1
    got = []
    for _ in range(count):
        st["pulls"] += 1
        st["since_ssr"] += 1
        forced = st["since_ssr"] >= PITY_THRESHOLD
        if forced:
            ssr = [i for i, it in enumerate(pool) if it["rarity"] == "SSR"]
            idx = rng.choice(ssr)
        else:
            idx = rng.choices(range(len(pool)), weights=weights, k=1)[0]
        item = dict(pool[idx])
        item["forced"] = forced
        st["since_ssr"] = 0 if item["rarity"] == "SSR" else st["since_ssr"]
        got.append(item)
        st["history"].append(item["rarity"])
    if len(st["history"]) > 200:
        st["history"] = st["history"][-200:]
    return st, got


# --------------------------------------------------------------------------
# dice
# --------------------------------------------------------------------------

def normalise_notation(raw):
    """Fix up what a query string does to dice notation.

    In a URL query a literal ``+`` decodes to a space, so ``?dice=3d6+2``
    arrives as ``"3d6 2"``. People also type ``2d6 x 3`` and ``2d6 + 3``.
    This maps those spellings onto one canonical form: lowercase, no spaces,
    and a ``+`` wherever a space separated two terms.
    """
    s = (raw or "").strip().lower()
    if not s:
        return ""
    s = s.replace("*", "x")                  # 2d6*3 is the same as 2d6 x 3
    s = re.sub(r"\s*x\s*", "x", s)          # collapse " x " to "x"
    s = s.replace("x", " ")                  # and treat it as a separator
    s = re.sub(r"\s+", " ", s)
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch != " ":
            out.append(ch)
            i += 1
            continue
        j = i
        while j < len(s) and s[j] == " ":
            j += 1
        prev = out[-1] if out else ""
        nxt = s[j] if j < len(s) else ""
        if prev in "+-" and nxt.isdigit():
            pass                             # "2d6+ 3" -> "2d6+3"
        elif prev.isdigit() and nxt.isdigit():
            out.append("+")                  # "3d6 2" -> "3d6+2"
        elif nxt in "+-" and prev.isdigit():
            pass                             # "2d6 -1" -> "2d6-1"
        else:
            out.append(" ")
        i = j
    return "".join(out).strip()


def roll_dice(notation, rng=random):
    """Roll dnd-style dice notation.

    Returns ``(total, rolls, modifiers, ok)``. Accepted: ``2d6+3``, ``d20``,
    ``4D8-2``, ``2d20+5-3``, ``2d6 x 3``, ``1d20+1d4``. The total is always
    ``sum(rolls) + sum(modifiers)``; a leading minus on a dice term negates it,
    which is how disadvantage dice are expressed.
    """
    text = normalise_notation(notation)
    if not text or " " in text:
        return 0, [], [], False
    if re.search(r"[^0-9a-z+\\-]", text):
        return 0, [], [], False
    if not re.search(r"d", text):
        return 0, [], [], False              # a bare number is not a roll
    # Two dice terms must be separated by a sign: "d20d20" is a typo, not a
    # request for forty dice, and guessing which the user meant is worse than
    # saying it did not parse.
    if re.search(r"\d\s*d|d\s*\d", text.replace("dd", "d")) and \
            not re.fullmatch(r"[+\-]?\d*d\d+([+\-]\d+)*", text) and \
            not re.fullmatch(r"[+\-]?\d*d\d+([+\-](\d+d\d+|\d+))*", text):
        return 0, [], [], False

    # tokenise: dice terms and bare numbers, each with a leading sign
    TERM = re.compile(r"([+\-]?)(\d*)d(\d*)|([+\-]?)(\d+)")
    pos = 0
    rolls = []
    mods = []
    total = 0
    saw_dice = False
    while pos < len(text):
        m = TERM.match(text, pos)
        if not m:
            return 0, [], [], False            # stray character
        pos = m.end()
        if m.group(2) is not None:            # a dice term
            saw_dice = True
            count = int(m.group(2) or 1)
            sides = int(m.group(3) or 0)
            if sides < 2:
                return 0, [], [], False       # d0, d1, bare "d"
            count = max(1, min(count, 100))
            sides = min(sides, 1000)
            sign = -1 if m.group(1) == "-" else 1
            for _ in range(count):
                v = rng.randint(1, sides)
                rolls.append(v)
                total += sign * v
        else:                                  # a modifier
            sign = -1 if m.group(4) == "-" else 1
            val = sign * int(m.group(5))
            mods.append(val)
            total += val
    if not saw_dice:
        return 0, [], [], False
    return total, rolls, mods, True


# --------------------------------------------------------------------------
# 15-puzzle
# --------------------------------------------------------------------------

def is_solvable(board):
    """Solvability for an even-width sliding puzzle with the goal row
    1..n-1, 0 (the blank) last. Classic inversion-parity test."""
    flat = [v for v in board if v != 0]
    n = int(round(len(board) ** 0.5))
    if n * n != len(board):
        return False
    inversions = 0
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            if flat[i] > flat[j]:
                inversions += 1
    blank_row_from_bottom = n - (board.index(0) // n)
    if n % 2 == 1:
        return inversions % 2 == 0
    return (inversions + blank_row_from_bottom) % 2 == 1


def new_puzzle(size=4, shuffle=80, rng=random):
    size = max(2, min(int(size), 6))
    board = list(range(1, size * size)) + [0]
    for _ in range(shuffle):
        a = rng.randrange(len(board))
        nb = puzzle_neighbours(board, a)
        b = rng.choice(nb)
        board[a], board[b] = board[b], board[a]
    # An even number of random swaps can leave the board unsolvable. To fix
    # it, swap two NON-BLANK tiles that sit in different rows: that flips the
    # inversion parity while leaving the blank's row (the other half of the
    # test) untouched. Moving the blank instead does not work - it changes
    # both terms and they cancel out.
    if not is_solvable(board):
        rows = {}
        for i, v in enumerate(board):
            if v:
                rows.setdefault(i // size, []).append(i)
        pair = [i for cells in rows.values() for i in cells[:1]]
        if len(pair) >= 2:
            a, b = pair[0], pair[1]
            board[a], board[b] = board[b], board[a]
    return {
        "game": "puzzle",
        "size": size,
        "board": board,
        "moves": 0,
        "opened": time.time(),
    }


def puzzle_neighbours(board, idx):
    n = int(round(len(board) ** 0.5))
    row, col = divmod(idx, n)
    out = []
    if row > 0:
        out.append(idx - n)
    if row < n - 1:
        out.append(idx + n)
    if col > 0:
        out.append(idx - 1)
    if col < n - 1:
        out.append(idx + 1)
    return out


def puzzle_text(board, size):
    goal = list(range(1, size * size)) + [0]
    if board == goal:
        return "Solved!"
    return "\n".join(
        " ".join((str(board[r * size + c]) if board[r * size + c] else "_")
                 .rjust(2) for c in range(size))
        for r in range(size))


def puzzle_moves(st, index):
    n = st["size"]
    if not (0 <= index < n * n):
        return st, "Tile index out of range."
    if st["board"][index] == 0:
        return st, "That is the blank."
    nb = puzzle_neighbours(st["board"], index)
    if index not in nb:
        return st, "That tile cannot slide there."
    blank = [i for i in nb if st["board"][i] == 0][0]
    st["board"][blank], st["board"][index] = st["board"][index], st["board"][blank]
    st["moves"] += 1
    goal = list(range(1, n * n)) + [0]
    if st["board"] == goal:
        return st, "Solved in %d moves!" % st["moves"]
    return st, "Moved. %d moves so far." % st["moves"]


def puzzle_hint(st):
    """The single tile that can legally move right now - enough to unstick
    a stuck player without solving the whole puzzle."""
    board = st["board"]
    blank = board.index(0)
    for idx in puzzle_neighbours(board, blank):
        v = board[idx]
        goal_idx = v - 1 if v else None
        if goal_idx is None:
            continue
        r, c = divmod(blank, st["size"])
        gr, gc = divmod(goal_idx, st["size"])
        if abs(r - gr) + abs(c - gc) == 1:
            return "Slide the tile %d (it belongs %s the blank)." % (
                v, "next to" if abs(r - gr) + abs(c - gc) == 1 else "")
    return "No single move gets closer right now."


# --------------------------------------------------------------------------
# minesweeper
# --------------------------------------------------------------------------

def new_mines(mines=10, size=9, rng=random):
    size = max(5, min(int(size), 30))
    count = max(1, min(int(mines), size * size - 9))
    # first click is always safe: place the mines after the fact
    cells = size * size
    return {
        "game": "minesweeper",
        "size": size,
        "mines": count,
        "board": [None] * cells,      # None = hidden, -1 = mine, int = count
        "opened": [],
        "flags": [],
        "first": True,
        "dead": False,
        "moves": 0,
        "opened_at": time.time(),
    }


def mines_reveal(st, index, rng=random):
    """Flood fill, the way the real game works: a zero opens its neighbours."""
    n = st["size"]
    if st["dead"]:
        return st, "The board already exploded."
    if not (0 <= index < n * n):
        return st, "Cell out of range."
    if index in st["opened"] or index in st["flags"]:
        return st, "That cell is already handled."

    if st["first"]:
        st["first"] = False
        # choose mines anywhere except the first click and its neighbours
        safe = {index} | set(
            k for k in _grid_neighbours(index, n) if True)
        pool = [i for i in range(n * n) if i not in safe]
        if len(pool) < st["mines"]:
            st["mines"] = len(pool)
        for i in rng.sample(pool, st["mines"]):
            st["board"][i] = -1
        for i in range(n * n):
            if st["board"][i] is None:
                st["board"][i] = sum(
                    1 for k in _grid_neighbours(i, n) if st["board"][k] == -1)
        st["mines"] = sum(1 for v in st["board"] if v == -1)

    st["moves"] += 1
    stack = [index]
    while stack:
        i = stack.pop()
        if i in st["opened"] or st["board"][i] == -1:
            continue
        st["opened"].append(i)
        if st["board"][i] == 0:
            for k in _grid_neighbours(i, n):
                if k not in st["opened"] and st["board"][k] != -1:
                    stack.append(k)
    if st["board"][index] == -1:
        st["dead"] = True
        return st, "Boom - that was a mine."
    left = n * n - len(st["opened"]) - st["mines"]
    if left <= 0:
        return st, "Cleared! You survived in %d moves." % st["moves"]
    return st, "Safe. %d cells left." % left


def _grid_neighbours(idx, n):
    row, col = divmod(idx, n)
    out = []
    if row > 0:
        out.append(idx - n)
    if row < n - 1:
        out.append(idx + n)
    if col > 0:
        out.append(idx - 1)
    if col < n - 1:
        out.append(idx + 1)
    return out


def mines_text(st):
    n = st["size"]
    cells = []
    for i in range(n * n):
        if i in st["flags"]:
            cells.append("F")
        elif i in st["opened"]:
            v = st["board"][i]
            cells.append("*" if v == -1 else str(v))
        else:
            cells.append("?")
    return "\n".join(" ".join(cells[r * n:(r + 1) * n]) for r in range(n))
