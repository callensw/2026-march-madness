#!/usr/bin/env python3
"""First Four teams: Texas, Howard, Miami OH, Prairie View A&M"""

first_four_teams = [
    {
        "name": "Texas",
        "seed": 11,
        "region": "West",
        "adj_o": 125.8,
        "adj_d": 96.3,
        "adj_tempo": 69.8,
        "record": "18-14",
        "conference": "SEC",
        "kenpom_rank": 37,
        "three_pt_pct": 35.3,
        "last_10_record": "5-5",
        "current_streak": "L3",
        "conference_tourney_result": "Lost SEC first round to Ole Miss 66-76",
        "recent_form_notes": "Elite offense (KenPom AdjO 13th) but defense struggles; won 5 straight in Feb then collapsed with 4 losses in last 5",
    },
    {
        "name": "Howard",
        "seed": 16,
        "region": "Midwest",
        "adj_o": 103.4,
        "adj_d": 97.2,
        "adj_tempo": 69.5,
        "record": "23-10",
        "conference": "MEAC",
        "kenpom_rank": 207,
        "three_pt_pct": 34.5,
        "last_10_record": "9-1",
        "current_streak": "W8",
        "conference_tourney_result": "MEAC Champion (beat SC State 78-61, beat NC Central 70-63)",
        "recent_form_notes": "Program-record 23 wins; won MEAC regular season and tournament titles; dominant 8-game win streak",
    },
    {
        "name": "Miami OH",
        "seed": 11,
        "region": "Midwest",
        "adj_o": 123.9,
        "adj_d": 102.8,
        "adj_tempo": 71.5,
        "record": "31-1",
        "conference": "MAC",
        "kenpom_rank": 93,
        "three_pt_pct": 39.2,
        "last_10_record": "9-1",
        "current_streak": "L1",
        "conference_tourney_result": "Lost MAC QF to UMass 83-87 (ended 31-0 regular season)",
        "recent_form_notes": "Went 31-0 in regular season (3rd team in D-I history); elite shooting (39.2% 3PT); only loss in MAC tourney QF",
    },
    {
        "name": "Prairie View A&M",
        "seed": 16,
        "region": "South",
        "adj_o": 100.2,
        "adj_d": 103.8,
        "adj_tempo": 70.6,
        "record": "18-17",
        "conference": "SWAC",
        "kenpom_rank": 288,
        "three_pt_pct": 33.4,
        "last_10_record": "9-1",
        "current_streak": "W7",
        "conference_tourney_result": "SWAC Champion as 8-seed (beat Bethune-Cookman 71-67, Alabama A&M 74-55, Southern 72-66)",
        "recent_form_notes": "First 8-seed to win SWAC tourney in conference history; 7-game win streak; Horne and Joseph combine for nearly 40 PPG",
    },
]

first_four_players = [
    # === TEXAS ===
    {"team_name": "Texas", "player_name": "Dailyn Swain", "position": "F", "year": "Jr", "points_per_game": 17.8, "rebounds_per_game": 7.6, "assists_per_game": 3.4, "fg_pct": 0.551, "three_pt_pct": 0.345, "ft_pct": 0.816, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "primary scorer, leads team in PPG/RPG/APG/SPG", "nba_draft_prospect": True},
    {"team_name": "Texas", "player_name": "Matas Vokietaitis", "position": "C", "year": "So", "points_per_game": 15.5, "rebounds_per_game": 6.8, "assists_per_game": 0.6, "fg_pct": 0.631, "three_pt_pct": 0.0, "ft_pct": 0.696, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "interior force, elite FG%, rim finisher", "nba_draft_prospect": False},
    {"team_name": "Texas", "player_name": "Tramon Mark", "position": "G", "year": "Sr", "points_per_game": 13.5, "rebounds_per_game": 3.4, "assists_per_game": 1.9, "fg_pct": 0.470, "three_pt_pct": 0.323, "ft_pct": 0.747, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "veteran scoring guard", "nba_draft_prospect": False},
    {"team_name": "Texas", "player_name": "Jordan Pope", "position": "G", "year": "Sr", "points_per_game": 13.3, "rebounds_per_game": 2.2, "assists_per_game": 1.9, "fg_pct": 0.405, "three_pt_pct": 0.375, "ft_pct": 0.840, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "best 3PT shooter, floor spacer", "nba_draft_prospect": False},
    {"team_name": "Texas", "player_name": "Camden Heide", "position": "F", "year": "Jr", "points_per_game": 6.2, "rebounds_per_game": 2.7, "assists_per_game": 0.6, "fg_pct": 0.500, "three_pt_pct": 0.459, "ft_pct": 0.706, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "3PT specialist (45.9%)", "nba_draft_prospect": False},

    # === HOWARD ===
    {"team_name": "Howard", "player_name": "Bryce Harris", "position": "G", "year": "Sr", "points_per_game": 17.1, "rebounds_per_game": 6.9, "assists_per_game": 2.5, "fg_pct": 0.484, "three_pt_pct": 0.374, "ft_pct": 0.779, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "MEAC POY, MEAC Tourney MOP", "nba_draft_prospect": False},
    {"team_name": "Howard", "player_name": "Cedric Taylor III", "position": "G", "year": "Jr", "points_per_game": 17.1, "rebounds_per_game": 6.7, "assists_per_game": 3.3, "fg_pct": 0.454, "three_pt_pct": 0.280, "ft_pct": 0.803, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "co-leading scorer, versatile guard", "nba_draft_prospect": False},
    {"team_name": "Howard", "player_name": "Cam Gillus", "position": "G", "year": "Jr", "points_per_game": 10.6, "rebounds_per_game": 4.3, "assists_per_game": 4.6, "fg_pct": 0.434, "three_pt_pct": 0.379, "ft_pct": 0.772, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "floor general, lead facilitator", "nba_draft_prospect": False},
    {"team_name": "Howard", "player_name": "Ose Okojie", "position": "G", "year": "Sr", "points_per_game": 10.5, "rebounds_per_game": 3.8, "assists_per_game": 1.7, "fg_pct": 0.566, "three_pt_pct": 0.429, "ft_pct": 0.624, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "efficient scorer, elite 3PT (42.9%)", "nba_draft_prospect": False},
    {"team_name": "Howard", "player_name": "Travelle Bryson", "position": "F", "year": "So", "points_per_game": 8.8, "rebounds_per_game": 3.4, "assists_per_game": 0.9, "fg_pct": 0.465, "three_pt_pct": 0.227, "ft_pct": 0.816, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "interior presence, developing big", "nba_draft_prospect": False},

    # === MIAMI OH ===
    {"team_name": "Miami OH", "player_name": "Peter Suder", "position": "G", "year": "Sr", "points_per_game": 14.6, "rebounds_per_game": 4.6, "assists_per_game": 4.0, "fg_pct": 0.554, "three_pt_pct": 0.429, "ft_pct": 0.725, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "MAC POY, elite efficiency, complete player", "nba_draft_prospect": False},
    {"team_name": "Miami OH", "player_name": "Brant Byers", "position": "F", "year": "So", "points_per_game": 14.2, "rebounds_per_game": 4.1, "assists_per_game": 0.6, "fg_pct": 0.489, "three_pt_pct": 0.398, "ft_pct": 0.786, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "All-MAC, versatile scoring forward", "nba_draft_prospect": False},
    {"team_name": "Miami OH", "player_name": "Evan Ipsaro", "position": "G", "year": "Jr", "points_per_game": 13.9, "rebounds_per_game": 2.4, "assists_per_game": 3.3, "fg_pct": 0.571, "three_pt_pct": 0.394, "ft_pct": 0.824, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "elite shooting guard, high efficiency", "nba_draft_prospect": False},
    {"team_name": "Miami OH", "player_name": "Eian Elmer", "position": "F", "year": "Jr", "points_per_game": 12.6, "rebounds_per_game": 6.0, "assists_per_game": 1.2, "fg_pct": 0.500, "three_pt_pct": 0.434, "ft_pct": 0.763, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "All-MAC, top rebounder, inside-outside", "nba_draft_prospect": False},
    {"team_name": "Miami OH", "player_name": "Antwone Woolfolk", "position": "F", "year": "Sr", "points_per_game": 10.3, "rebounds_per_game": 5.5, "assists_per_game": 1.5, "fg_pct": 0.640, "three_pt_pct": 0.344, "ft_pct": 0.566, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "interior finisher, elite FG%", "nba_draft_prospect": False},

    # === PRAIRIE VIEW A&M ===
    {"team_name": "Prairie View A&M", "player_name": "Dontae Horne", "position": "G", "year": "Sr", "points_per_game": 20.2, "rebounds_per_game": 4.5, "assists_per_game": 3.1, "fg_pct": 0.448, "three_pt_pct": 0.317, "ft_pct": 0.798, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "primary scorer, 30-pt SWAC tourney games", "nba_draft_prospect": False},
    {"team_name": "Prairie View A&M", "player_name": "Tai'Reon Joseph", "position": "G", "year": "Sr", "points_per_game": 18.2, "rebounds_per_game": 2.4, "assists_per_game": 1.0, "fg_pct": 0.411, "three_pt_pct": 0.307, "ft_pct": 0.763, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "secondary scorer, high-volume shooter", "nba_draft_prospect": False},
    {"team_name": "Prairie View A&M", "player_name": "Cory Wells", "position": "F", "year": "Sr", "points_per_game": 13.1, "rebounds_per_game": 7.1, "assists_per_game": 2.2, "fg_pct": 0.393, "three_pt_pct": 0.370, "ft_pct": 0.735, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "top rebounder, double-double threat", "nba_draft_prospect": False},
    {"team_name": "Prairie View A&M", "player_name": "Lance Williams", "position": "G", "year": "Sr", "points_per_game": 10.1, "rebounds_per_game": 3.2, "assists_per_game": 3.3, "fg_pct": 0.448, "three_pt_pct": 0.431, "ft_pct": 0.796, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "facilitator, best 3PT shooter (43.1%)", "nba_draft_prospect": False},
    {"team_name": "Prairie View A&M", "player_name": "Doug Young", "position": "G", "year": "Sr", "points_per_game": 9.3, "rebounds_per_game": 2.3, "assists_per_game": 1.7, "fg_pct": 0.444, "three_pt_pct": 0.364, "ft_pct": 0.750, "is_starter": True, "is_injured": False, "injury_details": None, "role_description": "veteran guard, reliable contributor", "nba_draft_prospect": False},
]
