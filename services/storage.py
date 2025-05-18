from sqlalchemy import create_engine, Table, Column, Text, MetaData
engine = create_engine("sqlite:///guild.db")
meta = MetaData()
papers = Table("papers", meta,
    Column("id", Text, primary_key=True),
    Column("title", Text), Column("summary", Text),
    Column("pdf_url", Text),
    Column("embedding", Text)  # JSON list
)
meta.create_all(engine)
