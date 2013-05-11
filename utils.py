'''
calibre_plugins.comicvine - A calibre metadata source for comicvine
'''
import logging
import re

import pycomicvine

from calibre.ebooks.metadata.book.base import Metadata
from calibre.utils import logging as calibre_logging # pylint: disable=W0404

# Optional Import for fuzzy title matching
try:
  import Levenshtein
except ImportError:
  pass

class CalibreHandler(logging.Handler):
  '''
  python logging handler that directs messages to the calibre logging
  interface
  '''
  def emit(self, record):
    level = getattr(calibre_logging, record.levelname)
    calibre_logging.default_log.prints(level, record.getMessage())

def build_meta(log, issue_id):
  '''Build metadata record based on comicvine issue_id'''
  issue = pycomicvine.Issue(issue_id, field_ids=[
      'id', 'name', 'volume', 'issue_number', 'person_credits', 'description', 
      'publisher', 'store_date', 'cover_date'])
  if not issue:
    log.warn('Unable to load Issue(%d)' % issue_id)
    return None
  title = '%s #%d' %  (issue.volume.name, issue.issue_number)
  if issue.name: 
    title = title + ': %s' % (issue.name)
  authors = [p.name for p in issue.person_credits]
  meta = Metadata(title, authors)
  meta.series = issue.volume.name
  meta.series_index = str(issue.issue_number)
  meta.set_identifier('comicvine', str(issue.id))
  meta.comments = issue.description
  meta.has_cover = False
  meta.publisher = issue.volume.publisher.name
  meta.pubdate = issue.store_date or issue.cover_date
  return meta

def find_volumes(volume_title, log):
  '''Look up volumes matching title string'''
  log.debug('Looking up volume: %s' % volume_title)
  candidate_volumes = pycomicvine.Volumes.search(
    query=volume_title, field_list=['id', 'name', 'count_of_issues'])
  log.debug('found %d matches' % len(candidate_volumes))
  return candidate_volumes

def find_issues(candidate_volumes, issue_number, log):
  '''Find issues in candidate volumes matching issue_number'''
  candidate_issues = []
  for volume in candidate_volumes:
    issue_filter = ['volume:%d' % volume.id]
    log.debug('checking candidate Volume(%s[%d])' % (volume.name, volume.id))
    if issue_number:
      issue_filter.append('issue_number:%d' % issue_number)
    filter_string = ','.join(issue_filter)
    log.debug('Searching for Issues(%s)' % filter_string)
    candidate_issues = candidate_issues + list(
      pycomicvine.Issues(
        filter=filter_string, field_ids=['id', 'volume', 'issue_number']))
    log.debug('%d matches found' % len(candidate_issues))
  return candidate_issues

def normalised_title(query, title):
  '''
  returns (issue_number,title_tokens)
  
  This method takes the provided title and breaks it down into
  searchable components.  The issue number should be preceeded by a
  '#' mark or it will be treated as a word in the title.  Anything
  provided after the issue number (e.g. a sub-title) will be
  ignored.
  '''
  def strip_abbrev(match):
    return match.string.replace('.', '')
  title_tokens = []
  issue_number = None
  volume = re.compile(r'^(?i)(v|vol)#?\d+$')
  abbrev = re.compile(r'(?i)((?:(?:\w).){3,})')
  title = abbrev.sub(strip_abbrev, title)
  for token in query.get_title_tokens(title):
    if volume.match(token):
      continue
    if token.startswith('#'):
      token = token.strip('#:')
    if token.isdigit():
      issue_number = int(token)
      break # Stop processing at issue number
    else:
      title_tokens.append(token.lower())
  return issue_number, title_tokens

def find_title(query, title, log):
  '''Extract volume name and issue number from issue title'''
  (issue_number, title_tokens) = normalised_title(query, title)
  candidate_volumes = find_volumes(' '.join(title_tokens), log)
  return (issue_number, candidate_volumes)

def find_authors(query, authors, log):
  '''Find people matching author string'''
  candidate_authors = []
  author_name = ' '.join(query.get_author_tokens(authors))
  if author_name and author_name != 'Unknown':
    log.debug("Searching for author: %s" % author_name)
    candidate_authors = pycomicvine.People(
      filter='name:%s' % (author_name), 
      field_list=['id', 'name'])
    log.debug("%d matches found" % len(candidate_authors))
  return candidate_authors

def score_title(metadata, title=None, issue_number=None, title_tokens=None):
  '''
  Calculate title matching ranking
  '''
  score = 0
  volume = '%s #%s' % (metadata.series.lower(), metadata.series_index)
  match_year = re.compile(r'\((\d{4})\)')
  year = match_year.search(title)
  if year and metadata.pubdate:
    score += abs(metadata.pubdate.year - int(year.group(1)))
  score += abs(len(volume) - len(title))
  for token in title_tokens:
    if token not in volume:
      score += 10
    try:
      similarity = Levenshtein.ratio(unicode(volume), unicode(title))
      score += 100 - int(100 * similarity)
    except NameError:
      pass
    if metadata.series_index != issue_number:
      score += 20
    if metadata.series_index not in title:
      score += 10
  return score

def keygen(metadata, title=None, authors=None, identifiers=None, **kwargs):
  '''
  Implement multi-result comparisons.
  
  1. Prefer an entry where the comicvine id matches
  2. Prefer similar titles using Levenshtein ratio (if module available)
  3. Penalise entries where the issue number is not in the title
  4. Prefer matching authors (the more matches, the higher the preference)
  '''
  score = 0
  if identifiers:
    try:
      if metadata.get_identifier('comicvine') == identifiers['comicvine']:
        return 0
    except (KeyError, AttributeError):
      pass
  if title:
    score += score_title(metadata, title=title, **kwargs)
  if authors:
    for author in authors:
      if author not in metadata.authors:
        score += 10
  return score
