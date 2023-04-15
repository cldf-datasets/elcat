# Releasing the ElCat CLDF data

0. Remove the results of the last web-crawl:
   ```shell
   rm -rf raw/html
   ```
1. Crawl the website:
   ```shell
   cldfbench download cldfbench_elcat.py
   ```
2. Re-create the CLDF data:
   ```shell
   cldfbench makecldf --with-zenodo --with-cldfreadme cldfbench_elcat.py --glottolog-version v4.7
   ```
3. Validate the data:
   ```shell
   pytest
   ```
4. Make sure an SQLite database can be created:
   ```shell
   cldf createdb cldf/StructureDataset-metadata.json elcat.sqlite
   ```
5. Re-create the README:
   ```shell
   cldfbench readme cldfbench_elcat.py
   ```
6. Commit, tag, push.
7. Create a release on GitHub