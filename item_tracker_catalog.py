import item_tracker as tracker

# Bump the item parser policy after expanding the static catalog with all
# D2R World set pieces/groups. This forces one clean Season 15 reparse of
# previously-seen topics, then subsequent runs remain incremental.
tracker.SOURCE_POLICY = "season15-items-static-catalog-v3"
tracker.main()
