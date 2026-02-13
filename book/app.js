// // import express from 'express'
// // import cors from 'cors'

// // import bookroutes from './books/routes/books.routes.js'

// // const app = express()

// // const port=3000

// // app.use(cors())
// // app.use(express.json())

// // app.use('/books', bookroutes)

// // if(process.env.NODE_ENV !== 'test'){
// //     app.listen(port, () => console.log(`[server]: server is running at http://localhost:${port}`))

// // }
// // export default app


// import express from 'express'
// import cors from 'cors'

// import bookRoutes from './books/routes/books.routes.js'

// const app = express()

// const port =3000

// app.use(cors())

// app.use(express.json())

// app.use('/books', bookRoutes)

// if(process.env.NODE_ENV !== 'test')
// {
//     app.listen(port, () => console.log(`[server]: server is running at http://localhost:${port}`))

// }

// export default app



import express from 'express'
import cors from 'cors'

import bookRoutes from './books/routes/books.routes.js'

const app = express()

const port=3000


app.use(cors())

app.use(express.json())

app.use('/books', bookRoutes)

if(process.env.NODE_ENV !== 'test')
{
    app.listen(port, () => console.log(`[server]: server is running at http://localhost:${port}`))
}

export default app