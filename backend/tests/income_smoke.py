"""Behavior checks for conditional progress, with isolated database records."""
from types import SimpleNamespace
from app.api.v1 import applications as a
from app.api.v1.fields import _dictionary

class DB:
    def __init__(self, values): self.values = values
    def get(self, model, key):
        return SimpleNamespace(value=self.values.get('employmentStatus'))
    def scalars(self, query): return SimpleNamespace(all=lambda: [])

original_owned, original_serialise = a._owned, a._serialise
a._owned=lambda *args: SimpleNamespace(application_id='preview', status='draft')

def money_step(values, employment=None):
    data={'fields':{k:{'value':v} for k,v in values.items()},'declarations':{},'employment':employment or []}
    a._serialise=lambda *args:data
    return next(s for s in a.progress('preview',DB(values),SimpleNamespace())['steps'] if s['id']=='money')

assert money_step({'employmentStatus':'Retired'})['complete']
assert money_step({'employmentStatus':'Not currently employed','notEmployedIncome':'0'})['complete']
assert 'At least one employer' in money_step({'employmentStatus':'Employed'})['missing']
assert money_step({'employmentStatus':'Employed'},[{'employer_name':'Demo Employer'}])['complete']
assert not money_step({'employmentStatus':'Self-employed'})['complete']
self_values={'employmentStatus':'Self-employed','businessName':'Demo','businessType':'Consulting','businessStartDate':'2020-01-01','ownershipPercent':'100','selfEmploymentIncome':'0'}
assert money_step(self_values)['complete']
assert not money_step({**self_values,'ownershipPercent':'101'})['complete']
assert not money_step({'employmentStatus':'Retired','pensionIncome':'-5'})['complete']
assert not money_step({'employmentStatus':'Other'})['complete']
assert money_step({'employmentStatus':'Other','otherSituation':'Investment income'})['complete']
assert not money_step({'employmentStatus':'Retired','retirementIncome':'NaN'})['complete']
for group in _dictionary()['steps'][4]['groups']:
    for field in group.get('fields',[]): assert field in _dictionary()['fields']
print('PASS: 12 conditional-income, validation and field-reference checks')
