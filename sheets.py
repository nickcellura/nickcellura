# Version 1.2
#   - Added support to create and download the computed file
#   - Added support to show multiple sheets and tabs
#   - Added support to allow multiple columns for a row

import gspread
import sys
#from oauth2client.service_account import ServiceAccountCredentials
import flask
from flask import Flask, session, jsonify, render_template, request, send_from_directory, Response, send_file
import json
import pandas as pd
import datetime
import hashlib
import httplib2
from apiclient import discovery, errors
from oauth2client import client
from gspread_dataframe import get_as_dataframe, set_with_dataframe

app = Flask(__name__, static_url_path='', static_folder='templates/')
app.secret_key = "secret key"

topline = ['Industry']
deal = ['Banker? Y/N', 'HQ Location', '1 Yr Growth Rate', '2 Yr Growth Rate', '3 Yr Growth Rate', 'RETENTION', 'EMPLOYEE HEADCOUNT', 'EV']
balance_sheet = ['CASH', 'ACCOUNTS RECEIVABLE', 'OTHER CURRENT ASSETS', 'Total current assets', 'PP&E', 'INTANGIBLES', 'OTHER LT ASSETS', 'Total LT Assets', 'Total Assets', \
        'ACCOUNTS PAYABLE', 'ACCRUED LIABILITIES', 'OTHER CURRENT LIABILITIES', 'DEFERRED REVENUE', 'CURRENT DEBT', 'Total Current liabilities', \
        'LT DEFERRED REVENUE', 'DEBT', 'OTHER LT LIABILITIES', 'Total Long Term Liabilities', 'Total Liabilities', 'EQUITY' ]
revs = [ 
        ['0-2000', '0-2M'], 
        ['2001-3500', '2M-3.5M'], 
        ['3501-10000', '3.55M-10M'], 
        ['10001-20000', '10M-20M'], 
        ['20001-40000', '20M-40M'],
        ['40001-100000000', '40M-100M'],
        ['100000000-1000000000', '>100M'] ]


def authClient():
    # Latest oAuth2 using credentials and a service role as Editor
#    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
#    creds = ServiceAccountCredentials.from_json_keyfile_name('creds.json', scope)
#    return gspread.authorize(creds)
    credentials = client.OAuth2Credentials.from_json(flask.session['credentials'])
    cred = credentials.authorize(httplib2.Http())
    gauth = gspread.authorize(credentials)
    drive = discovery.build('drive', 'v3', cred)
    return drive, gauth

def readTimes():
    try:
        with open('.time', 'r') as fp:
            return fp.read()
    except Exception as e:
        return '000'

def recordTimes(h):
    with open ('.time', 'w') as fp:
        fp.write(h)

def getRealTimes(gs):
    params = {
        'q': "mimeType='application/vnd.google-apps.spreadsheet'",
        "pageSize": 1000,
        'supportsTeamDrives': True,
        'includeTeamDriveItems': True,
        'fields':'files(id, name, modifiedTime)',
    }
    res = gs.request('get', 'https://www.googleapis.com/drive/v3/files', params=params).json()
    csum = hashlib.sha256(str(res).encode()).hexdigest()
    return csum

def readSheets(gs, seed):
    orderedDfs = {}
    for f in seed:
        sheet = gs.open(f['name'])
        print ('reading sheet: ' + sheet.title)
        for tab in sheet.worksheets():
            tabname = sheet.title + '-' + tab.title
            tabname = tabname[0:30]
            orderedDfs[tabname] = pd.DataFrame(tab.get_all_values())
    return orderedDfs

def filterTabsByVal(df, row_name, vals, col_no=1):
    if len(vals) == 0:
        return df
    newDF = {}
    for key in df:
        temp = df[key]
        if row_name == 'Industry':
            if temp[temp.field==row_name].values[0][col_no] in vals:
                newDF[key] = df[key]
        elif row_name == 'Total Revenue':
            try:
                row_val = int(temp[temp.field==row_name].values[0][5].replace(',', ''))
                print ('checking revenue value -- ' + str(row_val))
                for revenue in vals:
                    if row_val >= int(revenue.split('-')[0]) and row_val <= int(revenue.split('-')[1]):
                        newDF[key] = df[key]
            except Exception as e:
                pass
        else:
            try:
                row_val = float(temp[temp.field==row_name].values[0][5].replace('%', ''))
                if 'positive' in vals and row_val > 0:
                    newDF[key] = df[key]
                if 'negative' in vals and row_val < 0:
                    newDF[key] = df[key]
            except Exception as e:
                pass
    return newDF

def filterTabs(df, tabnames):
    newDF = {}
    for name in tabnames:
        newDF[name] = df[name]
    return newDF

def dropTabs(df, tabnames):
    newDF = {}
    for key in df:
        if key not in tabnames:
            newDF[key] = df[key]
    return newDF

def dumpToXL(oDf, filename):
    xl_file = pd.ExcelWriter(filename)
    for key in oDf:
        print ('dumping tab:' + key)
        tabname = key[0:30]
        oDf[tabname].to_excel(xl_file, tabname, index=False)
    xl_file.save()

def readFromXL(filename):
    df = pd.read_excel(filename, sheet_name=None)
    for key in df:
        df[key].fillna('', inplace=True)
    return df

def getTabNames(df):
    sheets = {}
    for key in df:
        sheetname, tabname = key.split('-')
        if sheetname not in sheets:
            sheets[sheetname] = []
        sheets[sheetname].append(tabname)
    return sheets

def getRows(df):
    iterator = iter(df)
    for idx, item in enumerate(iterator):
        if idx is 1:
            return set(df[item]['field'].tolist())
    return []

def getCols(df, rowno):
    try:
        iterator = iter(df)
        for idx, item in enumerate(iterator):
            if idx is 1:
                return [ str(x).split('.')[0] for x in df[item].iloc[rowno, :].tolist() ]
        return []
    except Exception as e:
        return [ 'No data found in row : ' + str(rowno) ]

def getFilterVals(df, row_name, col_no=1):
    vals = []
    for key in df:
        tdf = df[key]
        try:
            val = tdf[tdf.field==row_name].values[0][col_no]
            if val:
                vals.append(val) 
        except Exception as e:
            print (e)
    return vals

def getVals(df, row_name, col_no=1):
    keyvals = []
    vals = []
    for key in df:
        tdf = df[key]
        try:
            val = tdf[tdf.field==row_name].values[0][col_no]
            if val:
                vals.append(float(val.replace(',','')))
            else:
                vals.append(0.0)
        except Exception as e:
            print (e)
            vals.append(val)
        keyvals.append(key)
    return keyvals, vals

def genColNames(count):
    return [ 'col_'+str(i) for i in range(count) ]

def addColName(df, rowname):
    for key in df:
        col_names = genColNames(df[key].shape[1])
        col_names[0] = rowname
        df[key].columns = col_names

def writeToXL (keys, vals, filename, create=True):
    df = pd.DataFrame(vals, columns=keys)
    df.to_excel(filename)
    if create:
        drive, gs = authClient()
        gs.create(filename)
        ws = gs.open(filename).sheet1
        set_with_dataframe(ws, df)


def getFolders(drive, fid):
    flist = []
    for f in drive.files().list(q="mimeType='application/vnd.google-apps.folder' and parents in '"+fid+"' and trashed=false").execute().get('files'):
        subs = getFolders(drive, f['id'])
        if subs:
            flist += subs
        else:
            flist.append(f)
    return flist

@app.route("/")
def init():
    # Authenticate and redirect if necessary
    if 'credentials' not in flask.session:
        return flask.redirect(flask.url_for('oauth2callback'))

    # Successfuly authenticated!
    parent_id = 0
    drive, gauth = authClient()
    files = drive.files().list(q="mimeType='application/vnd.google-apps.folder'").execute()
    for f in files.get('files'):
        if f['name'] == 'Model Analysis':
            parent_id = f['id']
            break
    sheets = []
    for folder in getFolders(drive, parent_id):
        for f in drive.files().list(q="mimeType='application/vnd.google-apps.spreadsheet' and parents in '"+folder['id']+"' and trashed=false").execute().get('files'):
            sheets.append(f)

    operands = [ '/', '*', 'AVG' ]
    xlfile = 'main.xlsx'
    default_col_no = 10
    current_times = getRealTimes(gauth)
    try:
        if current_times == readTimes():
            print ('TIME: current')
            df = readFromXL(xlfile)
        else:
            print ('TIME: new modifications')
            dumpToXL(readSheets(gauth, sheets), xlfile)
            recordTimes(current_times)
            df = readFromXL(xlfile)
    except Exception as e:
        dumpToXL(readSheets(gauth, sheets), xlfile)
        recordTimes(current_times)
        df = readFromXL(xlfile)

    addColName(df, 'field')
    vals = getFilterVals(df, 'Industry')
    rows = set(getRows(df)) - set(balance_sheet) - set(deal) - set(topline)
    return render_template('index.html', tabs=getTabNames(df), rows=rows, balance_sheet=balance_sheet, deal=deal, cols=getCols(df, default_col_no), industry=vals, revenues=revs, operands=operands)

@app.route("/getxls/<filename>", methods=["GET", "POST"])
def getxls(filename):
    return send_file(filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, cache_timeout=-1)

@app.route("/calculate", methods=["GET", "POST"])
def calculate():
    operands = [ '/', '*', 'AVG' ]
    xlfile = 'main.xlsx'
    default_col_no = 10
    df = readFromXL(xlfile)
    addColName(df, 'field')
    stack = json.loads(request.args.get('stack'))
    tabs = json.loads(request.args.get('tabs'))
    save_flag = json.loads(request.args.get('save'))
    filterlist = json.loads(request.args.get('filterlist'))

    cols = getCols(df, default_col_no)
    print ('stack:' + str(stack))
    print ('tabs:' + str(tabs))
    print ('filterlist:' + str(filterlist))

    # First filter by tab names
    if tabs:
        df = filterTabs(df, tabs)

    # Run the topline filter over the filtered tabs for further filtering
    filter_vals = {}
    filter_vals['Industry'] = []
    filter_vals['Total Revenue'] = []
    filter_vals['Ebitda %'] = []
    for name in filterlist:
        filter_row = name.split('_')[0]
        filter_vals[filter_row].append(name.split('_')[1])

    df = filterTabsByVal(df, 'Industry', filter_vals['Industry']) 
    df = filterTabsByVal(df, 'Total Revenue', filter_vals['Total Revenue']) 
    if len(filter_vals['Ebitda %']) == 1:
        df = filterTabsByVal(df, 'Ebitda % ', filter_vals['Ebitda %'])

    print ('final filtered tab list ------------->' + str([x for x in df]))
    r_type = 'left'
    op_type = operands[0]
    json_output = { "left_vals": [], "right_vals": [], "compute": 0, "saved_file": ''}
    row_name = ''
    for idx, item in enumerate(stack):
        el_type = item.split('_')[0]
        vals = []
        if el_type == 'row':
            row_name = item.split('_')[1]
            keyvals, vals = getVals(df, row_name)
            try:
                vals.append(sum(vals))
                vals.append(sum(vals)/len(vals))
            except Exception as e:
                vals.append('NA')
                vals.append('NA')
            vals = [ row_name ] + vals
        elif el_type == 'col':
            if not row_name:
                continue
            col_name = item.split('_')[1]
            col_no = cols.index(col_name) 
            keyvals, vals = getVals(df, row_name, col_no)
            json_output[r_type+'_vals'].pop()
            try:
                vals.append(sum(vals))
                vals.append(sum(vals)/len(vals))
            except Exception as e:
                vals.append('NA')
                vals.append('NA')
            vals = [ row_name + '(' + col_name + ')' ] + vals
        elif el_type == 'operand':
            op_name = item.split('_')[1]
            op_no = operands.index(op_name)
            op_type = operands[op_no]
            r_type = 'right'
        json_output[r_type+'_vals'].append(vals)
        json_output[r_type+'_keys'] = [ x.split('-')[1] for x in keyvals ]
        print (json_output)

    if r_type == "right" and len(json_output['right_vals']) and json_output['right_vals'][0][-1] != 0:
        if op_type == '/': 
                json_output['compute'] = float(json_output['left_vals'][0][-1]) / float(json_output['right_vals'][0][-1])
        elif op_type == '*': 
                json_output['compute'] = float(json_output['left_vals'][0][-1]) * float(json_output['right_vals'][0][-1])
        elif op_type == 'AVG': 
                json_output['compute'] = float(json_output['left_vals'][0][-1]) / float(json_output['right_vals'][0][-1])
    if save_flag:
        filename = 'compute_'+str(datetime.datetime.now())+'.xlsx'
        writeToXL(['Object'] + json_output['left_keys'] + ['Sum'] + ['Avg'], json_output['left_vals'] + json_output['right_vals'], filename)
        json_output['saved_file'] =  filename
    return json_output

@app.route('/oauth2callback')
def oauth2callback():
    flow = client.flow_from_clientsecrets(
        'client_secrets.json',
        scope='https://www.googleapis.com/auth/drive',
        redirect_uri=flask.url_for('oauth2callback', _external=True)
    )
    if 'code' not in flask.request.args:
        auth_uri = flow.step1_get_authorize_url()
        return flask.redirect(auth_uri)
    else:
        auth_code = flask.request.args.get('code')
        credentials = flow.step2_exchange(auth_code)
        flask.session['credentials'] = credentials.to_json()
        return flask.redirect(flask.url_for('init'))
app.run(host='0.0.0.0', port=80)
