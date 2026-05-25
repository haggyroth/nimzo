"""
Sample PGN fixtures for tests.
All games are short, legal, and have known properties.
"""

# Scholar's mate — White wins in 4 moves
SCHOLARS_MATE = """[Event "Test"]
[White "Model A"]
[Black "Model B"]
[Result "1-0"]

1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6?? 4. Qxf7# 1-0"""

# Fool's mate — Black wins in 2 moves (fastest possible)
FOOLS_MATE = """[Event "Test"]
[White "Model A"]
[Black "Model B"]
[Result "0-1"]

1. f3 e5 2. g4 Qh4# 0-1"""

# Stalemate draw — a known stalemate position reached via short sequence
STALEMATE_DRAW = """[Event "Test"]
[White "Model A"]
[Black "Model B"]
[Result "1/2-1/2"]

1. e3 a5 2. Qh5 Ra6 3. Qxa5 h5 4. h4 Rah6 5. Qxc7 f6 6. Qxd7+ Kf7 7. Qxb7 Qd3 8. Qxb8 Qh7 9. Qxc8 Kg6 10. Qe6 1/2-1/2"""

# Longer middlegame — 20-move game with a resign
MIDGAME_RESIGN = """[Event "Test"]
[White "Model A"]
[Black "Model B"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6
8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 11. Nbd2 Bb7 12. Bc2 Re8 13. Nf1 Bf8
14. Ng3 g6 15. a4 c5 16. d5 c4 17. b4 cxb3 18. Bxb3 Nc5 19. Bc2 bxa4
20. Rxa4 1-0"""

# A game that opens with the Ruy Lopez (ECO C60-range)
RUY_LOPEZ_START = """[Event "Test"]
[White "Model A"]
[Black "Model B"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 *"""

# Sicilian opening (ECO B20-range)
SICILIAN_START = """[Event "Test"]
[White "Model A"]
[Black "Model B"]
[Result "*"]

1. e4 c5 *"""
