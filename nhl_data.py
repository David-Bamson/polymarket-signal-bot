import requests

API_KEY = "72d0facdc03c7d99141b5b71c7d0b4f8"

def get_nhl_standings():
    url = "https://v1.hockey.api-sports.io/standings"
    headers = {"x-apisports-key": API_KEY}
    
    response = requests.get(url, headers=headers, params={"league": "57", "season": "2024"})
    data = response.json()
    
    standings = {}
    
    for stage in data["response"]:
        for team in stage:
            if team["stage"] != "NHL - Regular Season":
                continue
            if team["group"]["name"] not in ["Eastern Conference", "Western Conference"]:
                continue
            
            name = team["team"]["name"]
            standings[name] = {
                "position": team["position"],
                "points": team["points"],
                "win_pct": float(team["games"]["win"]["percentage"]),
                "made_playoffs": "Play Offs" in (team["description"] or "")
            }
    
    return standings

standings = get_nhl_standings()
for team, data in standings.items():
    print(f"{team}: Pos {data['position']} | Pts {data['points']} | Win% {data['win_pct']} | Playoffs: {data['made_playoffs']}")