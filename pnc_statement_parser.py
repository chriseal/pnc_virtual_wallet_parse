import pandas as pd
import numpy as np
from scipy.stats import percentileofscore

import os
import textract # http://textract.readthedocs.io/en/latest/python_package.html
import re
import unicodedata
import string
import datetime


linebreak_p = re.compile(r'\r|\n|\x0c')
long_whitespace_p = re.compile(r'[\r\n\t\f\v]|   ')
MY_p = re.compile(r'\d{2}\/\d{2}')
printable = set(string.printable)

OUTPUT_FOLDER = './../pnc_outputs_aldkfjldkfj_data'
if not os.path.exists(OUTPUT_FOLDER):
	os.mkdir(OUTPUT_FOLDER)


def get_fname_from_fpath(save_to_fpath):
	return save_to_fpath.split("/")[-1].split('.')[0]


def rm_custom_chars_lower(txt, row_starts_in_colIdx1=False):
	""" # remove commas and dollar signs so that it's easier to match numerics """

	m = re.match('   ', txt)
	if bool(m):
		if m.start() == 0:
			if row_starts_in_colIdx1:
				txt = re.sub(' ', '_', txt, count=1)

	return txt.replace(',', '').replace('$',' ').lower().strip()


def add_long_whitespace_bf_numeric(lines):
	""" """

	numeric_at_end_p = re.compile(r"(-?\d+(\.\d+)?)$")
	for l_idx, l in enumerate(lines):
		l2 = re.sub(numeric_at_end_p, "                "+"\\1", l)
		if l2 != l:
			lines[l_idx] = l2

	return lines


def remove_long_whitespace_and_replace_with_delimiter(lines, split_p):
	""" """

	new_lines, max_cols = [], 0
	for l in lines:
		nl = []
		for s in split_p.split(l):
			if len(s) > 0:
				nl.append(s.strip().replace(',', '')) # for easier conversion to float
		if len(nl) > max_cols:
			max_cols = len(nl)
		new_lines.append(nl)

	return new_lines, max_cols


def ensure_equal_number_of_columns(lines, max_cols):
	""" list of lists"""

	for line_idx, line in enumerate(lines):
		cols_to_add = max_cols - len(line)
		if cols_to_add > 0:
			for _ in range(cols_to_add):
				line.append('')
			lines[line_idx] = line

	return lines


def convert_to_dataframe_coerce_to_float(lines):
	""" """

	df = pd.DataFrame(lines)
	for col in df.columns:
		df[col] = df.loc[:, col].apply(lambda x: try_to_convert_to_numeric(x))
		df[col] = df.loc[:, col].apply(lambda x: try_to_convert_to_numeric(x)) # needs to run twice, in case of unicode

	return df



def normalize_unicode(txt):
	""" get the best ascii representation of the text """

	# TODO - change this when converting to PYTHON 3
	if type(txt) == unicode:
		return unicodedata.normalize('NFKD', txt).encode('ascii','ignore')
	else:
		return txt

def get_printable_text(txt):
	""" printable ascii only """

	return str(''.join([c for c in normalize_unicode(txt).replace("\xc2\xa0", ' ').replace("\xe2\x80\x90", ' ') if c in printable]))


def convert_to_printable_text(val, float_to_int=True):
	""" take in any val and return printable text """

	if float_to_int:
		if type(val) == float:
			if np.isnan(val):
				val = ''
			else:
				val = int(round(val, 0))

	try:
		return str(get_printable_text(val)).lower()
	except:
		return str(get_printable_text(str(val))).lower()

def try_to_convert_to_numeric(x):
	""" """

	try:
		return float(x)
	except:
		try:
			return int(round(x, 0))
		except:
			return convert_to_printable_text(x)


# MAIN FUNCTIONS =======================================================================


def combine_monthly_statements_for_year(folder_path, year_to_analyze, save_to_fpath):
	"""
	For traditional accounts, aggregate monthly csv exports from PNC into a filterable spreadsheet.
	As of March 2018, PNC allows month-by-month monthly export of transaction activity in traditional accounts

	Aggregate from a folder of monthly activity csv exports from PNC.com for a given year (i.e. 12 files, if the account was open all year)

	combine_monthly_statements_for_year(folder_path, year_to_analyze, save_to_fpath)
	"""

	dfs = []
	for f in os.listdir(os.path.join(folder_path)):
		df = pd.read_csv(os.path.join(folder_path, f), skiprows=1, header=None)
		df.columns = ['date', 'amount', 'desc', '1','2', 'type']
		dfs.append(df)

	df = pd.concat(dfs, ignore_index=True, sort=False)
	df.drop_duplicates(inplace=True)
	df['date'] = df['date'].apply(lambda x: pd.to_datetime(x))
	mask_keep = df['date'].apply(lambda x: x.year == year_to_analyze)
	df = df[mask_keep].copy()

	debit = df.query("type == 'DEBIT'").copy()
	debit.rename(columns={'amount': 'debit'}, inplace=True)
	debit['credit'] = None
	credit = df.query("type == 'CREDIT'").copy()
	credit.rename(columns={'amount': 'credit'}, inplace=True)
	credit['debit'] = None

	df = pd.concat([debit, credit], ignore_index=True, sort=False)
	df.sort_values(by='date', ascending=True, inplace=True)
	df.reset_index(inplace=True, drop=True)
	df = df[['date', 'debit', 'credit', 'desc', 'type', '1', '2']].copy()
	df['debit'] = df['debit'].fillna(0.)
	df['credit'] = df['credit'].fillna(0.)
	df['debit'] = df['debit'].astype(float)
	df['credit'] = df['credit'].astype(float)
	df['account'] = get_fname_from_fpath(save_to_fpath)

	df.to_csv(save_to_fpath, index=False)


def parse_pnc_statement_pdf(folder_path, year_to_analyze, save_to_fpath):
	""" For virtual wallet accounts, parse monthly statements (in pdf form) and then aggregate into a filterable spreadsheet.
	As of March 2018, PNC.com has no means of exporting csv's for transaction activity in virtual accounts.

	Aggregate a folder of pdf monthly statements from PNC.com for input into a spreadsheet for easy filtering and categorization.

	parse_pnc_statement_pdf(folder_path, year_to_analyze, save_to_fpath)
	"""

	dfs = []
	for f in os.listdir(folder_path):
		text = textract.process(os.path.join(folder_path, f), method='pdftotext', layout=True).decode('utf8').lower()
		lines = linebreak_p.split(text)
		leading_space_cnt = pd.Series([len(l) - len(l.strip()) for l in lines])
		leading_space_cnt_percs = leading_space_cnt.apply(lambda x: percentileofscore(leading_space_cnt.values, x))
		leading_space_cnt_50thPerc = np.percentile(leading_space_cnt.values, 50.)
		rows_that_start_in_colIdx1 = pd.Series(leading_space_cnt.index).apply(lambda x: leading_space_cnt_percs[x] >= 90. and leading_space_cnt[x] > 3*leading_space_cnt_50thPerc)
		rows_that_start_in_colIdx1 = leading_space_cnt[rows_that_start_in_colIdx1].index.tolist()

		new_lines = []
		for l_idx, l in enumerate(lines):
			if not bool(re.match(r'\r|\n|\x0c', l)) and len(l) > 0 and 'page' not in l.lower():
				row_starts_in_colIdx1 = False
				if l_idx in rows_that_start_in_colIdx1:
					row_starts_in_colIdx1 = True
				if l_idx+1 < len(lines):
					if l.startswith('                   '):
						l += lines[l_idx+1].strip()
				new_lines.append(rm_custom_chars_lower(l, row_starts_in_colIdx1=row_starts_in_colIdx1))

		categories = {
			'balance summary': False,
			'transaction summary': False,
			'interest summary': False,
			'deposits and other additions': True,
			'checks and substitute checks': True,
			'banking/check card withdrawals and purchases': True,
			'online and electronic banking deductions': True,
			'daily balance detail': False}
		current_category = ''
		rows = []
		period_found = False
		for l_idx, l in enumerate(new_lines):
			if 'for the period' in l and not period_found:
				period = re.search(r'\d{2}\/\d{2}\/\d{4} to \d{2}\/\d{2}\/\d{4}', l)
				period = l[period.start():period.end()]
				start = datetime.datetime.strptime(period.split(' to ')[0], '%m/%d/%Y')
				end = datetime.datetime.strptime(period.split(' to ')[-1], '%m/%d/%Y')
				period_found = True
				continue

			if not period_found:
				continue

			for cat in categories.keys():
				if l.startswith(cat):
					current_category = cat

			if current_category in categories.keys():
				if categories[current_category]:
					if re.match(MY_p, l.strip()):
						l = '         '.join([l, current_category])
						values = l.split('  ')
						row = {}
						remaining_values = []
						for val_idx, value in enumerate(values):
							if val_idx == 0:
								month = int(value.split('/')[0])
								day = int(value.split('/')[1])
								if start.year == end.year:
									row['date'] = datetime.datetime(year=year_to_analyze, month=month, day=day)
								else:
									if month == 1:
										date_year = end.year
									elif month == 12:
										date_year = start.year
									row['date'] = datetime.datetime(year=date_year, month=month, day=day)
								continue
							try:
								row['amount'] = float(value)
								continue
							except:
								pass

							if val_idx == len(values)-1:
								row['category'] = value.strip()
								continue

							if bool(value):
								remaining_values.append(value)

						row['description'] = ' '.join([r.strip() for r in remaining_values])
						rows.append(row)

		df = pd.DataFrame(rows)
		dfs.append(df)

	df = pd.concat(dfs, ignore_index=True, sort=False)
	df.sort_values(by='date', ascending=True, inplace=True)
	mask_keep = df['date'].apply(lambda x: x.year == year_to_analyze)
	df = df[mask_keep].copy()
	df.drop_duplicates(inplace=True)
	df['account'] = get_fname_from_fpath(save_to_fpath)
	df.to_csv(save_to_fpath, index=False)


if __name__ == '__main__':
	"""
	# RUN IN IPYTHON, example
	year_to_analyze = 2017
	combine_monthly_statements_for_year(
		'./data/transactions 2017 acct xxxx', year_to_analyze, './data/acctxxxx_2017.csv')
	combine_monthly_statements_for_year(
		'./data/transactions 2017 acct yyyy', year_to_analyze, './data/acctyyyy_2017.csv')
	parse_pnc_statement_pdf('./data/spend account', year_to_analyze, './data/spend_acctzzzz_2017.csv')
	"""

	year_to_analyze = 2019
	combine_monthly_statements_for_year('/home/chriseal/Documents/taxes_2019/csvs/lilc_2343/', 
		year_to_analyze, os.path.join(OUTPUT_FOLDER, 'lilc_2343.csv') )
	combine_monthly_statements_for_year('/home/chriseal/Documents/taxes_2019/csvs/dsllc_7088/', 
		year_to_analyze, os.path.join(OUTPUT_FOLDER, 'dsllc_7088.csv') )
	parse_pnc_statement_pdf('/home/chriseal/Documents/taxes_2019/paper_statements/spend_8676',
		year_to_analyze, os.path.join(OUTPUT_FOLDER, 'spend_8676.csv') )