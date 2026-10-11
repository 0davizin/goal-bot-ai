"""Experimental ESPN soccer scoreboard reader. No Telegram signals."""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from typing import Any
import requests

BASE_URL = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
STAT_NAMES = ('totalShots', 'shotsOnTarget', 'wonCorners', 'possessionPct', 'foulsCommitted')


def fetch_matches(league: str = 'eng.1', date: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    params = {'limit': limit}
    if date:
        params['dates'] = date
    response = requests.get(f'{BASE_URL}/{league}/scoreboard', params=params, timeout=20)
    response.raise_for_status()
    events = response.json().get('events', [])
    if not isinstance(events, list):
        raise ValueError('ESPN: formato inesperado em events')
    return [normalize_event(event, league) for event in events]


def normalize_event(event: dict[str, Any], league: str) -> dict[str, Any]:
    competitions = event.get('competitions') or []
    competition = competitions[0] if competitions else {}
    teams = {}
    for competitor in competition.get('competitors') or []:
        role = competitor.get('homeAway', 'unknown')
        stats = {s.get('name'): s.get('displayValue') for s in competitor.get('statistics') or [] if s.get('name') in STAT_NAMES}
        teams[role] = {
            'name': (competitor.get('team') or {}).get('displayName'),
            'score': competitor.get('score'),
            'statistics': stats,
        }
    status = event.get('status') or {}
    return {
        'id': event.get('id'), 'league': league, 'league_id': (event.get('uid', '').split('~l:')[1].split('~')[0] if '~l:' in event.get('uid', '') else None), 'name': event.get('name'),
        'event_date': event.get('date'), 'status': (status.get('type') or {}).get('name'),
        'minute': status.get('displayClock'), 'home': teams.get('home'),
        'away': teams.get('away'), 'collected_at_utc': datetime.now(timezone.utc).isoformat(),
        'source': 'ESPN_UNOFFICIAL',
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='ESPN experimental collector; no signals')
    parser.add_argument('--liga', default='eng.1')
    parser.add_argument('--data', help='YYYYMMDD')
    parser.add_argument('--ao-vivo', action='store_true')
    args = parser.parse_args()
    if args.data and (len(args.data) != 8 or not args.data.isdigit()):
        parser.error('--data deve ter formato YYYYMMDD')
    try:
        games = fetch_matches(args.liga, args.data)
    except (requests.RequestException, ValueError) as exc:
        parser.exit(1, f'Erro na consulta ESPN: {exc}\n')
    if args.ao_vivo:
        games = [g for g in games if g['status'] in ('STATUS_FIRST_HALF', 'STATUS_SECOND_HALF', 'STATUS_HALFTIME', 'STATUS_EXTRA_TIME')]
    print(f'Jogos encontrados: {len(games)}')
    for game in games:
        print(json.dumps(game, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
