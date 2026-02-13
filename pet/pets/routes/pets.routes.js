import express from 'express';
import {
    listPets,
    getPet,
    editPets,
    addPet,
    deletePet,
} from '../controllers/pets.controllers.js';
const router = express.Router();

router.get("/", listPets);
router.get("/:id" ,getPet);
router.put("/:id", editPets);
router.post("/", addPet);
router.delete("/:id", deletePet);
export default router;