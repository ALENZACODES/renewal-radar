// Read in a browser on 2026-10-17 from https://www.bmo.com/bmocda/templates/json_mortgage_include.jsp
// (BMO's own rate file; dt_mortgage = 'October 17, 2026'). Fixed block as published.
var MORTGAGE = {'fixed' : {'6 month \x28convertible\x29' : {'frn_name':'6 mois \x28convertible\x29', 'value':'5.490', 'product_code':'home\x5fmtg\x5f9959', 'type':'convertible', 'term_months':'6'},
'6 month \x28open\x29' : {'frn_name':'6 mois \x28ouvert\x29', 'value':'9.950', 'product_code':'home\x5fmtg\x5f9958', 'type':'open', 'term_months':'6'},
'1 year \x28closed\x29' : {'frn_name':'1 an \x28fermé\x29', 'value':'5.490', 'product_code':'home\x5fmtg\x5f9961', 'type':'closed', 'term_months':'12'},
'1 year \x28open\x29' : {'frn_name':'1 an \x28ouvert\x29', 'value':'9.950', 'product_code':'home\x5fmtg\x5f9960', 'type':'open', 'term_months':'12'},
'2 year \x28closed\x29' : {'frn_name':'2 ans \x28fermé\x29', 'value':'4.940', 'product_code':'home\x5fmtg\x5f9962', 'type':'closed', 'term_months':'24'},
'3 year \x28closed\x29' : {'frn_name':'3 ans \x28fermé\x29', 'value':'6.050', 'product_code':'home\x5fmtg\x5f9963', 'type':'closed', 'term_months':'36'},
'4 year \x28closed\x29' : {'frn_name':'4 ans \x28fermé\x29', 'value':'5.990', 'product_code':'home\x5fmtg\x5f9964', 'type':'closed', 'term_months':'48'},
'5 year \x28closed\x29' : {'frn_name':'5 ans \x28fermé\x29', 'value':'6.090', 'product_code':'home\x5fmtg\x5f9965', 'type':'closed', 'term_months':'60'},
'6 year \x28closed\x29' : {'frn_name':'6 ans \x28fermé\x29', 'value':'6.290', 'product_code':'home\x5fmtg\x5f9968', 'type':'closed', 'term_months':'72'},
'7 year \x28closed\x29' : {'frn_name':'7 ans \x28fermé\x29', 'value':'6.400', 'product_code':'home\x5fmtg\x5f9969', 'type':'closed', 'term_months':'84'},
'10 year\x28closed\x29' : {'frn_name':'10 ans \x28fermé\x29', 'value':'6.800', 'product_code':'home\x5fmtg\x5f9970', 'type':'closed', 'term_months':'120'},
'18 year \x28open\x29' : {'frn_name':'18 ans \x28ouvert\x29', 'value':'8.500', 'product_code':'home\x5fmtg\x5f9972', 'type':'flexible below prime', 'term_months':'216'}}, //END fixed
'variable' : {}};
var dt_mortgage = {'en':'October 17, 2026', 'fr':'17 octobre 2026'};
