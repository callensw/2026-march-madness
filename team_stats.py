"""
2025-26 NCAA Tournament Team Stats: Turnover Rate and Opponent FG%

Sources:
- Turnovers per game: NCAA.com team stats (stat #217), updated through 3/13/2026
- Opponent FG%: NCAA.com / stats.ncaa.org Field Goal Percentage Defense (stat #149)
- Sports-Reference.com 2025-26 school stats and opponent stats
"""

team_stats = {
    # 1-seeds
    "Duke":             {"turnover_rate": 10.5, "opp_fg_pct": 0.392},
    "Arizona":          {"turnover_rate": 10.8, "opp_fg_pct": 0.392},
    "Michigan":         {"turnover_rate": 12.0, "opp_fg_pct": 0.384},
    "Florida":          {"turnover_rate": 11.9, "opp_fg_pct": 0.408},

    # 2-seeds
    "UConn":            {"turnover_rate": 11.2, "opp_fg_pct": 0.402},
    "Purdue":           {"turnover_rate":  8.9, "opp_fg_pct": 0.446},
    "Iowa State":       {"turnover_rate": 10.3, "opp_fg_pct": 0.426},
    "Houston":          {"turnover_rate":  8.5, "opp_fg_pct": 0.400},

    # 3-seeds
    "Michigan State":   {"turnover_rate": 11.5, "opp_fg_pct": 0.410},
    "Gonzaga":          {"turnover_rate":  9.7, "opp_fg_pct": 0.395},
    "Virginia":         {"turnover_rate": 10.8, "opp_fg_pct": 0.395},
    "Illinois":         {"turnover_rate":  8.9, "opp_fg_pct": 0.410},

    # 4-seeds
    "Kansas":           {"turnover_rate": 10.7, "opp_fg_pct": 0.388},
    "Arkansas":         {"turnover_rate":  9.0, "opp_fg_pct": 0.453},
    "Alabama":          {"turnover_rate":  9.8, "opp_fg_pct": 0.433},
    "Nebraska":         {"turnover_rate":  9.8, "opp_fg_pct": 0.404},

    # 5-seeds
    "St. John's":       {"turnover_rate": 10.5, "opp_fg_pct": 0.421},
    "Wisconsin":        {"turnover_rate":  8.9, "opp_fg_pct": 0.447},
    "Texas Tech":       {"turnover_rate": 10.8, "opp_fg_pct": 0.439},
    "Vanderbilt":       {"turnover_rate":  9.5, "opp_fg_pct": 0.427},

    # 6-seeds
    "Louisville":       {"turnover_rate": 11.6, "opp_fg_pct": 0.424},
    "BYU":              {"turnover_rate": 10.9, "opp_fg_pct": 0.443},
    "Tennessee":        {"turnover_rate": 11.7, "opp_fg_pct": 0.409},
    "UNC":              {"turnover_rate":  9.7, "opp_fg_pct": 0.418},

    # 7-seeds
    "UCLA":             {"turnover_rate":  8.9, "opp_fg_pct": 0.433},
    "Miami FL":         {"turnover_rate": 11.2, "opp_fg_pct": 0.445},
    "Kentucky":         {"turnover_rate": 10.5, "opp_fg_pct": 0.425},
    "Saint Mary's":     {"turnover_rate": 10.8, "opp_fg_pct": 0.405},

    # 8-seeds
    "Ohio State":       {"turnover_rate": 10.4, "opp_fg_pct": 0.439},
    "Villanova":        {"turnover_rate": 10.1, "opp_fg_pct": 0.450},
    "Georgia":          {"turnover_rate": 10.7, "opp_fg_pct": 0.438},
    "Clemson":          {"turnover_rate":  9.4, "opp_fg_pct": 0.419},

    # 9-seeds
    "TCU":              {"turnover_rate": 10.9, "opp_fg_pct": 0.446},
    "Utah State":       {"turnover_rate": 10.6, "opp_fg_pct": 0.424},
    "Saint Louis":      {"turnover_rate": 12.5, "opp_fg_pct": 0.379},
    "Iowa":             {"turnover_rate":  9.7, "opp_fg_pct": 0.461},

    # 10-seeds
    "UCF":              {"turnover_rate": 11.2, "opp_fg_pct": 0.456},
    "Missouri":         {"turnover_rate": 12.4, "opp_fg_pct": 0.436},
    "Santa Clara":      {"turnover_rate": 10.8, "opp_fg_pct": 0.451},
    "Texas A&M":        {"turnover_rate": 10.8, "opp_fg_pct": 0.442},

    # 11-seeds
    "USF":              {"turnover_rate": 11.2, "opp_fg_pct": 0.413},
    "NC State":         {"turnover_rate":  9.2, "opp_fg_pct": 0.450},
    "SMU":              {"turnover_rate": 11.3, "opp_fg_pct": 0.434},
    "VCU":              {"turnover_rate": 10.5, "opp_fg_pct": 0.431},
    "Texas":            {"turnover_rate": 11.0, "opp_fg_pct": 0.449},
    "Miami OH":         {"turnover_rate": 10.5, "opp_fg_pct": 0.436},

    # 12-seeds
    "Northern Iowa":    {"turnover_rate":  9.3, "opp_fg_pct": 0.407},
    "High Point":       {"turnover_rate":  9.4, "opp_fg_pct": 0.426},
    "Akron":            {"turnover_rate": 10.9, "opp_fg_pct": 0.421},
    "McNeese":          {"turnover_rate":  9.6, "opp_fg_pct": 0.407},

    # 13-seeds
    "Cal Baptist":      {"turnover_rate": 12.4, "opp_fg_pct": 0.417},
    "Hawaii":           {"turnover_rate": 13.5, "opp_fg_pct": 0.411},
    "Hofstra":          {"turnover_rate": 10.6, "opp_fg_pct": 0.387},
    "Troy":             {"turnover_rate": 11.9, "opp_fg_pct": 0.433},

    # 14-seeds
    "North Dakota State": {"turnover_rate": 10.8, "opp_fg_pct": 0.438},
    "Kennesaw State":   {"turnover_rate": 11.9, "opp_fg_pct": 0.407},
    "Wright State":     {"turnover_rate": 11.3, "opp_fg_pct": 0.457},
    "Penn":             {"turnover_rate": 10.8, "opp_fg_pct": 0.451},

    # 15-seeds
    "Furman":           {"turnover_rate": 11.9, "opp_fg_pct": 0.425},
    "Queens":           {"turnover_rate": 10.7, "opp_fg_pct": 0.466},
    "Tennessee State":  {"turnover_rate": 12.2, "opp_fg_pct": 0.444},
    "Idaho":            {"turnover_rate": 10.6, "opp_fg_pct": 0.431},

    # 16-seeds
    "Siena":            {"turnover_rate": 10.3, "opp_fg_pct": 0.422},
    "LIU":              {"turnover_rate": 13.0, "opp_fg_pct": 0.445},
    "UMBC":             {"turnover_rate":  9.6, "opp_fg_pct": 0.424},
    "Lehigh":           {"turnover_rate": 12.1, "opp_fg_pct": 0.446},
    "Howard":           {"turnover_rate": 13.5, "opp_fg_pct": 0.418},
    "Prairie View A&M": {"turnover_rate": 11.9, "opp_fg_pct": 0.437},
}
