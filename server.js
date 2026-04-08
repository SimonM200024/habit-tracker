require('dotenv').config();
const express = require('express');
const { BigQuery } = require('@google-cloud/bigquery');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

// Serve static files
app.use(express.static(path.join(__dirname)));

// BigQuery client
const bigquery = new BigQuery({
  projectId: process.env.BIGQUERY_PROJECT_ID || 'quick-cache-466013-v5',
});

const DATASET = process.env.BIGQUERY_DATASET || 'scraping';
const TABLE = process.env.BIGQUERY_TABLE || 'scraped_products_sql';
const FULL_TABLE = `\`${process.env.BIGQUERY_PROJECT_ID || 'quick-cache-466013-v5'}.${DATASET}.${TABLE}\``;

// API: Get products with pagination, search, and sorting
app.get('/api/products', async (req, res) => {
  try {
    const page = Math.max(1, parseInt(req.query.page) || 1);
    const limit = Math.min(100, Math.max(1, parseInt(req.query.limit) || 25));
    const offset = (page - 1) * limit;
    const search = req.query.search || '';
    const sortBy = req.query.sortBy || '';
    const sortOrder = (req.query.sortOrder || 'ASC').toUpperCase() === 'DESC' ? 'DESC' : 'ASC';

    // Get columns for the table first (cached after first call)
    const columns = await getTableColumns();

    // Build WHERE clause for search
    let whereClause = '';
    if (search) {
      const searchConditions = columns
        .filter(c => c.type === 'STRING')
        .map(c => `LOWER(CAST(\`${c.name}\` AS STRING)) LIKE LOWER(@search)`)
        .join(' OR ');
      if (searchConditions) {
        whereClause = `WHERE (${searchConditions})`;
      }
    }

    // Build ORDER BY clause
    let orderClause = '';
    if (sortBy && columns.some(c => c.name === sortBy)) {
      orderClause = `ORDER BY \`${sortBy}\` ${sortOrder}`;
    }

    // Count query
    const countQuery = `SELECT COUNT(*) as total FROM ${FULL_TABLE} ${whereClause}`;
    const params = search ? { search: `%${search}%` } : {};

    const [countRows] = await bigquery.query({ query: countQuery, params });
    const total = parseInt(countRows[0].total);

    // Data query
    const dataQuery = `SELECT * FROM ${FULL_TABLE} ${whereClause} ${orderClause} LIMIT @limit OFFSET @offset`;
    const [rows] = await bigquery.query({
      query: dataQuery,
      params: { ...params, limit, offset },
    });

    res.json({
      data: rows,
      columns: columns.map(c => c.name),
      columnTypes: columns.reduce((acc, c) => { acc[c.name] = c.type; return acc; }, {}),
      pagination: {
        page,
        limit,
        total,
        totalPages: Math.ceil(total / limit),
      },
    });
  } catch (error) {
    console.error('BigQuery error:', error);
    res.status(500).json({
      error: 'Failed to fetch products',
      message: error.message,
    });
  }
});

// API: Get table schema/columns
let cachedColumns = null;
async function getTableColumns() {
  if (cachedColumns) return cachedColumns;

  const dataset = bigquery.dataset(DATASET);
  const table = dataset.table(TABLE);
  const [metadata] = await table.getMetadata();
  cachedColumns = metadata.schema.fields.map(f => ({
    name: f.name,
    type: f.type,
  }));
  return cachedColumns;
}

app.get('/api/products/schema', async (req, res) => {
  try {
    const columns = await getTableColumns();
    res.json({ columns });
  } catch (error) {
    console.error('Schema error:', error);
    res.status(500).json({ error: 'Failed to fetch schema', message: error.message });
  }
});

// API: Get summary stats
app.get('/api/products/stats', async (req, res) => {
  try {
    const countQuery = `SELECT COUNT(*) as total FROM ${FULL_TABLE}`;
    const [countRows] = await bigquery.query({ query: countQuery });
    const total = parseInt(countRows[0].total);

    const columns = await getTableColumns();

    // Try to get stats for numeric columns
    const numericCols = columns.filter(c =>
      ['INTEGER', 'INT64', 'FLOAT', 'FLOAT64', 'NUMERIC', 'BIGNUMERIC'].includes(c.type)
    );

    let numericStats = {};
    if (numericCols.length > 0) {
      const statsCols = numericCols.slice(0, 5).map(c =>
        `MIN(\`${c.name}\`) as min_${c.name}, MAX(\`${c.name}\`) as max_${c.name}, AVG(\`${c.name}\`) as avg_${c.name}`
      ).join(', ');

      const statsQuery = `SELECT ${statsCols} FROM ${FULL_TABLE}`;
      const [statsRows] = await bigquery.query({ query: statsQuery });

      if (statsRows.length > 0) {
        for (const col of numericCols.slice(0, 5)) {
          numericStats[col.name] = {
            min: statsRows[0][`min_${col.name}`],
            max: statsRows[0][`max_${col.name}`],
            avg: statsRows[0][`avg_${col.name}`] !== null
              ? parseFloat(statsRows[0][`avg_${col.name}`]).toFixed(2)
              : null,
          };
        }
      }
    }

    res.json({ total, columns: columns.length, numericStats });
  } catch (error) {
    console.error('Stats error:', error);
    res.status(500).json({ error: 'Failed to fetch stats', message: error.message });
  }
});

app.listen(PORT, () => {
  console.log(`Life Tracker server running at http://localhost:${PORT}`);
  console.log(`Products API: http://localhost:${PORT}/api/products`);
  console.log(`BigQuery table: ${FULL_TABLE}`);
});
