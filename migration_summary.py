from playhouse.migrate import SqliteMigrator, migrate
import podcli

migrator = SqliteMigrator(podcli.db)

migrate(
    migrator.add_column('episodetable', 'summary',
                        podcli.EpisodeTable.summary))