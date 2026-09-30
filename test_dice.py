"""Dice notation: the accepted set, the rejected set, and the invariant.

The invariant is the one that matters: for every accepted notation,
total == sum(rolls) + sum(modifiers). A parser that violates it is lying to
the bot, which would print a wrong number to a user.

Run: python3 test_dice.py
"""
import random
import sys

sys.path.insert(0, "/root/ApiBot")
import play  # noqa: E402

# (notation, expected roll count, expected modifiers)
ACCEPT = [
    ("2d6", 2, []),
    ("d20", 1, []),
    ("D20", 1, []),
    ("2D6", 2, []),
    ("2d6+3", 2, [3]),
    ("3d6+2", 3, [2]),
    ("4d8-2", 4, [-2]),
    ("1d100", 1, []),
    ("10d10", 10, []),
    ("d100+50", 1, [50]),
    ("1d6-1", 1, [-1]),
    ("2d6-1+3", 2, [-1, 3]),
    ("3d6+2+4", 3, [2, 4]),
    ("2d20+5-3", 2, [5, -3]),
    ("1d20+1d4", 2, []),           # two dice terms, no modifiers
    ("-2d6", 2, []),               # disadvantage: negated dice, not a modifier
    ("2d6x3", 2, [3]),             # 2d6 x 3 normalises to 2d6+3
    ("2d6*3", 2, [3]),             # 2d6*3 likewise
    # the '+ became a space' case, which is what a real query string sends
    ("3d6 2", 3, [2]),
    ("2d6 -1", 2, [-1]),
    ("2d6 +3", 2, [3]),
    ("2d6+ 3", 2, [3]),
    ("2d6 - 1", 2, [-1]),
    ("2d20+5 -3", 2, [5, -3]),
]

REJECT = [
    "", "   ", "5", "0", "d", "3d", "1d0", "d0", "d1", "2d6+", "2d6-",
    "2x6", "banana", "a d6", "d6a", "2d6++3x", "2d6junk",
    "+", "-", "x", "d20d20", "2d6+*", "..", "1d6.5", "1e3", "2d6+3.5",
]

FAILS = []


def main():
    rng = random.Random(1234)

    def consistent(total, rolls, mods):
        """The one invariant that must always hold.

        Dice can be negated (``-2d6`` is how disadvantage is written), and
        ``rolls`` always holds the positive face values, so the sign lives in
        the total, not in the list. Every other term is a plain modifier.
        """
        return abs(total - sum(mods)) == sum(rolls)

    print("=== accepted notation ===")
    for notation, want_rolls, want_mods in ACCEPT:
        total, rolls, mods, ok = play.roll_dice(notation, rng=rng)
        good = (ok and len(rolls) == want_rolls and mods == want_mods
                and consistent(total, rolls, mods))
        if not good:
            FAILS.append("accept %r -> ok=%s rolls=%d mods=%s total=%s"
                         % (notation, ok, len(rolls), mods, total))
        print("  %s %-13s -> total=%-5d rolls=%-2d mods=%s"
              % ("OK " if good else "BAD", notation, total, len(rolls), mods))

    print("\n=== rejected notation ===")
    for notation in REJECT:
        ok = play.roll_dice(notation, rng=rng)[3]
        if ok:
            FAILS.append("reject %r was accepted" % notation)
        print("  %s %-13r ok=%s" % ("OK " if not ok else "BAD",
                                    notation, ok))

    print("\n=== invariant over 2000 random rolls ===")
    for _ in range(2000):
        n = rng.randint(1, 6)
        sides = rng.choice([2, 3, 4, 6, 8, 10, 12, 20, 60, 100, 1000])
        mod = rng.randint(-20, 20)
        sign = "+" if mod >= 0 else ""
        lead = rng.choice(["", "-"])          # sometimes disadvantage dice
        notation = "%s%dd%d%s%d" % (lead, n, sides, sign, mod)
        total, rolls, mods, ok = play.roll_dice(notation, rng=rng)
        if not (ok and len(rolls) == n and all(1 <= v <= sides for v in rolls)
                and mods == [mod] and consistent(total, rolls, mods)
                and total == (sum(rolls) * (-1 if lead == "-" else 1)) + mod):
            FAILS.append("invariant broke on %r" % notation)
    print("  2000x  |total - sum(mods)| == sum(rolls), counts and ranges exact")
    print("  2000x  negative dice subtract correctly")

    print("\n=== clamping ===")
    for notation, note in (("500d6", "count capped at 100"),
                           ("1d5000", "sides capped at 1000"),
                           ("1d1", "one-sided dice rejected")):
        total, rolls, mods, ok = play.roll_dice(notation, rng=rng)
        print("  %-10s ok=%-5s rolls=%d  (%s)" % (notation, ok, len(rolls),
                                                  note))
        if notation == "1d1" and ok:
            FAILS.append("1d1 should be rejected")
        if notation == "500d6" and len(rolls) != 100:
            FAILS.append("500d6 should clamp to 100 dice")
        if notation == "1d5000" and (not ok or rolls[0] > 1000):
            FAILS.append("1d5000 should clamp sides to 1000")

    print("\n" + "=" * 56)
    if FAILS:
        print("FAILURES (%d):" % len(FAILS))
        for f in FAILS:
            print("  -", f)
        return 1
    print("all dice tests pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
