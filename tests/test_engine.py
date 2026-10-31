from trader.engine import size_trade, ladder, plan_position


# --- sizing, checked against real trades in Dad's GOOGL sheet (Randol IRA, $5k basis) ---

def test_oct29_googl_buy_3():
    # held 14 @ $287.22 -> $4,021, $979 short of basis; he bought 3
    assert size_trade(14, 287.22, 5000, "BUY") == 3

def test_oct30_googl_buy_1():
    # held 17 @ $280.41 -> $4,767, just under $4,800; he bought 1
    assert size_trade(17, 280.41, 5000, "BUY") == 1

def test_apr15_2026_googl_sell_3():
    # held 18 @ $334 -> $6,012; he sold 3
    assert size_trade(18, 334.00, 5000, "SELL") == 3

def test_above_rounding_lands_at_or_above_basis():
    n = size_trade(14, 287.22, 5000, "BUY", rounding="above")
    assert n == 4 and (14 + n) * 287.22 >= 5000
    n = size_trade(18, 334.00, 5000, "SELL", rounding="above")
    assert (18 - n) * 334.00 >= 5000

def test_minimum_one_share_and_never_oversell():
    assert size_trade(18, 289.00, 5000, "SELL") == 1          # gap is 0.69 shares -> still 1
    assert size_trade(2, 10_000.0, 5000, "SELL") <= 2


# --- ladder ---

def test_googl_ladder_today():
    sells, buys = ladder(18, 5000, 200)
    assert sells[0].limit == 288.89 and sells[0].shares == 1     # 18 x 288.89 >= 5,200
    assert buys[0].limit == 266.66 and buys[0].shares == 1       # 18 x 266.66 <= 4,800
    assert sells[1].limit > sells[0].limit and buys[1].limit < buys[0].limit
    for r in sells + buys:
        # each rung returns the position near basis
        assert abs(r.after_value - 5000) < r.limit

def test_rung_prices_actually_trigger():
    for shares, basis, band in [(18, 5000, 200), (1539, 5000, 200), (16, 10000, 400), (3503, 5000, 200)]:
        sells, buys = ladder(shares, basis, band, levels=1)
        assert shares * sells[0].limit >= basis + band
        assert shares * buys[0].limit <= basis - band


# --- plan ---

def test_inside_band_gets_ladder_only():
    p = plan_position(18, 5000, 200, 280.48)
    assert p["status"] == "ok" and p["act_now"] is None and len(p["sells"]) == 2

def test_outside_band_acts_now_then_ladders_from_new_size():
    p = plan_position(14, 5000, 200, 287.22)
    assert p["status"] == "act_now"
    assert p["act_now"] == {"side": "BUY", "shares": 3, "limit": 287.22}
    assert p["buys"][0]["after_shares"] > 17     # ladder starts from 17 shares

def test_far_from_basis_is_flagged_not_laddered():
    p = plan_position(42, 5000, 200, 357.15)     # AGX Randol IRA: $15k on a $5k basis
    assert p["status"] == "review" and not p["sells"] and not p["buys"]
