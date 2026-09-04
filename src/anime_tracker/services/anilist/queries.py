from __future__ import annotations


MEDIA_FIELDS = """
id
idMal
title { romaji english native }
synonyms
format
status
season
seasonYear
startDate { year month day }
endDate { year month day }
episodes
duration
countryOfOrigin
source
genres
averageScore
popularity
coverImage { extraLarge large medium color }
bannerImage
siteUrl
description(asHtml: false)
isAdult
updatedAt
nextAiringEpisode { id episode airingAt timeUntilAiring }
relations {
  edges {
    relationType
    node { id format status season seasonYear episodes title { romaji english native } }
  }
}
"""

MEDIA_BY_ID_QUERY = f"""
query MediaById($id: Int!) {{
  Media(id: $id, type: ANIME) {{ {MEDIA_FIELDS} }}
}}
"""

MEDIA_BY_MAL_ID_QUERY = f"""
query MediaByMalId($malId: Int!) {{
  Media(idMal: $malId, type: ANIME) {{ {MEDIA_FIELDS} }}
}}
"""

MEDIA_SEARCH_QUERY = f"""
query SearchMedia($search: String!, $page: Int!, $perPage: Int!, $year: Int, $format: MediaFormat, $season: MediaSeason) {{
  Page(page: $page, perPage: $perPage) {{
    pageInfo {{ total currentPage lastPage hasNextPage perPage }}
    media(search: $search, type: ANIME, seasonYear: $year, format: $format, season: $season) {{ {MEDIA_FIELDS} }}
  }}
}}
"""

MEDIA_PAGE_QUERY = f"""
query MediaPage($ids: [Int], $page: Int!, $perPage: Int!) {{
  Page(page: $page, perPage: $perPage) {{
    pageInfo {{ total currentPage lastPage hasNextPage perPage }}
    media(id_in: $ids, type: ANIME) {{ {MEDIA_FIELDS} }}
  }}
}}
"""

RELATIONS_QUERY = f"""
query MediaRelations($id: Int!) {{
  Media(id: $id, type: ANIME) {{
    id
    relations {{
      edges {{
        relationType
        node {{ id format status title {{ romaji english native }} }}
      }}
    }}
  }}
}}
"""

AIRING_FIELDS = "id episode airingAt timeUntilAiring mediaId"

UPCOMING_AIRING_QUERY = f"""
query UpcomingAirings($from: Int!, $to: Int!, $page: Int!, $perPage: Int!) {{
  Page(page: $page, perPage: $perPage) {{
    pageInfo {{ hasNextPage currentPage lastPage }}
    airingSchedules(airingAt_greater: $from, airingAt_lesser: $to, sort: TIME) {{ {AIRING_FIELDS} }}
  }}
}}
"""

RECENT_AIRING_QUERY = f"""
query RecentAirings($from: Int!, $to: Int!, $page: Int!, $perPage: Int!) {{
  Page(page: $page, perPage: $perPage) {{
    pageInfo {{ hasNextPage currentPage lastPage }}
    airingSchedules(airingAt_greater: $from, airingAt_lesser: $to, sort: TIME_DESC) {{ {AIRING_FIELDS} }}
  }}
}}
"""
