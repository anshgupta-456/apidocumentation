import express from 'express';
import {
    listsBooks,
    getBooks,
    editBooks,
    addBooks,
    deleteBooks,
}from 'controller/books.controller.js';

const router = express.Router();

router.get("/", listsBooks);
router.get("/:id", getBooks);
router.put("/:id", editBooks);
router.post("/", addBooks);
router.delete("/:id", deleteBooks);
export default router;