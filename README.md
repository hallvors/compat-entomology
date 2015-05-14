Experimental project to see if we can expose compat test data in a way others can find useful.


## Database layout

dbinit.py sets up a number of MySQL tables:

* domains - assigns a number to each site we track. All other tables use values from domains.id to refer to a site
* testdata_sets - tracks each "submit" of data for a site. Each "submit" contains data for a single site only, but can contain multiple types of data - from regression tests via screenshots to css issues, and for several UAs and engines. Most other result tables have a data_set field which gets values from testdata_set.id
* redirects - tracks redirects during loading of a site. Redirects are stored as tab-separated URLs.
* regression_results - tracks per-bug regression tests and the results (true/false)
* js_problems - tracks JS execution errors
* screenshots - tracks submitted screenshots
* css_problems - issues with -webkit-style CSS, mostly
* test_data - tracks other data like Compatipede plugin test results
* comments - not really used yet, may be used either for comments related to reviewing specific screenshots, or commenting on stuff that may be a bug
* human_review - if we want to track "this site works fine" statements, for example by thums-up add-ons, here's  place to collect the data
* contacts - if we spider a site for compat problems we might just take a moment to look for public contact details - social media accounts etc.
* uastrings - helper table listing the UA strings we've seen results reported for. 

See dbdesc.json for details.
